extends Node
## Global signal bus. Keeps screens decoupled from the systems that drive them.

signal screen_changed(screen_name: String)
signal run_changed()          ## run state mutated
signal meta_changed()         ## resolve / unlocks / inventory / streak mutated
signal theme_changed()        ## active theme swapped; rebuild visuals
signal logged(text: String, kind: String)   ## kind: info | good | bad | warn
signal tick()                 ## roughly once a second, for deadline countdowns
