extends Node
## Global signal bus. Keeps screens decoupled from the systems that drive them.

signal screen_changed(screen_name: String)
signal run_changed()          ## run state mutated
signal meta_changed()         ## resolve / unlocks / inventory / streak mutated
signal theme_changed()        ## active theme swapped; rebuild visuals
signal logged(text: String, kind: String)   ## kind: info | good | bad | warn
signal tick()                 ## roughly once a second, for deadline countdowns
## Something opened up. Distinct from `logged` because an unlock is not a status
## line to be read and forgotten — it names a place the player can now go, and
## the toast that announces it is tappable. A player told the Hearth is open and
## then left to find it has been told nothing useful.
signal unlocked(text: String, screen: String)
