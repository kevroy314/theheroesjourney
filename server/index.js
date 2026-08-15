/* Push server for The Heroes' Journey.
 *
 * Deliberately small: one process, one JSON file, no database. It holds Web Push
 * subscriptions and a per-subscription list of "send this at that time"
 * reminders, and ticks once a minute to deliver whatever has come due.
 *
 * It never decides *what* to say — the game computes its own reminders and posts
 * the whole list, replacing whatever was there. That keeps all the scheduling
 * logic in one place (Notify.gd) and leaves this process as dumb plumbing.
 *
 * Routed same-origin as /push/* by the game's nginx, so the OAuth proxy in front
 * of the site protects these endpoints too.
 */
import express from "express";
import webpush from "web-push";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const PORT = Number(process.env.PORT || 8071);
const DATA = process.env.DATA_DIR || "./data";
const SUBS_FILE = path.join(DATA, "subscriptions.json");
const VAPID_FILE = path.join(DATA, "vapid.json");
const CONTACT = process.env.VAPID_CONTACT || "mailto:kevin.horecka@gmail.com";
const TICK_MS = 60_000;
const MAX_REMINDERS = 64;

fs.mkdirSync(DATA, { recursive: true });

/* ---------------------------------------------------------------- VAPID keys */
/* Generated once and kept. Rotating them invalidates every existing
 * subscription, so this file is the thing to back up. */
let vapid;
if (fs.existsSync(VAPID_FILE)) {
  vapid = JSON.parse(fs.readFileSync(VAPID_FILE, "utf8"));
} else {
  vapid = webpush.generateVAPIDKeys();
  fs.writeFileSync(VAPID_FILE, JSON.stringify(vapid, null, 2));
  console.log("[push] generated new VAPID keys in", VAPID_FILE);
}
webpush.setVapidDetails(CONTACT, vapid.publicKey, vapid.privateKey);

/* ------------------------------------------------------------------- storage */
let subs = fs.existsSync(SUBS_FILE) ? JSON.parse(fs.readFileSync(SUBS_FILE, "utf8")) : {};
let dirty = false;
const save = () => {
  if (!dirty) return;
  fs.writeFileSync(SUBS_FILE, JSON.stringify(subs, null, 2));
  dirty = false;
};
setInterval(save, 5_000).unref();

const idFor = (endpoint) => crypto.createHash("sha256").update(endpoint).digest("hex").slice(0, 16);

const DEFAULT_PREFS = {
  enabled: true,
  deadline: true,
  streak: true,
  quiet_start: 22,   // local hour when quiet time begins
  quiet_end: 8,      // local hour when it ends
  tz_offset: 0,      // minutes east of UTC, from the client
};

/* Is `when` (a unix ms) inside the player's quiet hours? */
function inQuietHours(when, prefs) {
  const local = new Date(when + prefs.tz_offset * 60_000);
  const hour = local.getUTCHours() + local.getUTCMinutes() / 60;
  const { quiet_start: start, quiet_end: end } = prefs;
  if (start === end) return false;
  return start < end ? hour >= start && hour < end : hour >= start || hour < end;
}

/* Push it to the far end of quiet hours rather than dropping it — a deadline
 * warning you never get is worse than one that arrives at breakfast. */
function afterQuietHours(when, prefs) {
  const local = new Date(when + prefs.tz_offset * 60_000);
  local.setUTCHours(prefs.quiet_end, 0, 0, 0);
  let out = local.getTime() - prefs.tz_offset * 60_000;
  if (out <= when) out += 86_400_000;
  return out;
}

/* --------------------------------------------------------------------- send */
async function deliver(id, entry, reminder) {
  const payload = JSON.stringify({
    title: reminder.title,
    body: reminder.body,
    tag: reminder.tag || reminder.kind || "hj",
    url: reminder.url || "./",
  });
  try {
    await webpush.sendNotification(entry.subscription, payload, { TTL: 3600 });
    console.log("[push] sent %s -> %s", reminder.kind, id);
    return true;
  } catch (err) {
    const code = err.statusCode;
    console.log("[push] failed %s -> %s (%s)", reminder.kind, id, code || err.message);
    // 404/410 mean the browser threw the subscription away. Stop trying.
    if (code === 404 || code === 410) {
      delete subs[id];
      dirty = true;
    }
    return false;
  }
}

async function tick() {
  const now = Date.now();
  for (const [id, entry] of Object.entries(subs)) {
    const prefs = { ...DEFAULT_PREFS, ...(entry.prefs || {}) };
    if (!prefs.enabled) continue;
    const keep = [];
    for (const reminder of entry.reminders || []) {
      if (reminder.at > now) { keep.push(reminder); continue; }
      if (prefs[reminder.kind] === false) continue;          // this kind is off
      if (now - reminder.at > 6 * 3600_000) continue;        // too stale to be useful
      if (inQuietHours(reminder.at, prefs)) {
        keep.push({ ...reminder, at: afterQuietHours(reminder.at, prefs) });
        continue;
      }
      await deliver(id, entry, reminder);
    }
    if (keep.length !== (entry.reminders || []).length) {
      entry.reminders = keep;
      dirty = true;
    }
  }
  save();
}
setInterval(() => { tick().catch((e) => console.error("[push] tick", e)); }, TICK_MS);

/* -------------------------------------------------------------------- routes */
const app = express();
app.use(express.json({ limit: "64kb" }));

app.get("/push/key", (_req, res) => res.json({ publicKey: vapid.publicKey }));

app.get("/push/health", (_req, res) =>
  res.json({ ok: true, subscriptions: Object.keys(subs).length }));

app.post("/push/subscribe", (req, res) => {
  const { subscription, prefs } = req.body || {};
  if (!subscription?.endpoint) return res.status(400).json({ error: "no subscription" });
  const id = idFor(subscription.endpoint);
  subs[id] = {
    subscription,
    prefs: { ...DEFAULT_PREFS, ...(subs[id]?.prefs || {}), ...(prefs || {}) },
    reminders: subs[id]?.reminders || [],
    seen: Date.now(),
  };
  dirty = true;
  save();
  res.json({ id });
});

app.post("/push/prefs", (req, res) => {
  const { id, prefs } = req.body || {};
  if (!subs[id]) return res.status(404).json({ error: "unknown subscription" });
  subs[id].prefs = { ...DEFAULT_PREFS, ...subs[id].prefs, ...(prefs || {}) };
  dirty = true;
  save();
  res.json({ ok: true, prefs: subs[id].prefs });
});

/* The game owns scheduling; this replaces the whole list every time. */
app.post("/push/schedule", (req, res) => {
  const { id, reminders } = req.body || {};
  if (!subs[id]) return res.status(404).json({ error: "unknown subscription" });
  subs[id].reminders = (reminders || [])
    .filter((r) => r && typeof r.at === "number" && r.title)
    .slice(0, MAX_REMINDERS);
  subs[id].seen = Date.now();
  dirty = true;
  save();
  res.json({ ok: true, count: subs[id].reminders.length });
});

app.post("/push/test", async (req, res) => {
  const { id } = req.body || {};
  if (!subs[id]) return res.status(404).json({ error: "unknown subscription" });
  const ok = await deliver(id, subs[id], {
    kind: "test",
    title: "The Heroes' Journey",
    body: "Notifications are working. This is the only one you asked for.",
  });
  res.json({ ok });
});

app.delete("/push/subscribe", (req, res) => {
  const { id } = req.body || {};
  if (subs[id]) { delete subs[id]; dirty = true; save(); }
  res.json({ ok: true });
});

app.listen(PORT, "0.0.0.0", () =>
  console.log("[push] listening on %d, %d subscription(s)", PORT, Object.keys(subs).length));
