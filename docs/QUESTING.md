# Quest information

This guide covers two related but different tasks:

1. inspecting a character's **live quest state** through the MCP bridge; and
2. deriving static quest steps from datamined game sheets.

The live client tells you what the character currently has and which sequence it
is on. Datamined game sheets tell you the actors, listeners, locations, unlocks,
and other static quest data needed to author or verify a profile.

## Data source and change history

Use the community repository:

- <https://github.com/xivapi/ffxiv-datamining>

It publishes CSVs extracted from FFXIV game data and keeps them in Git so patches
can be diffed. The repository README describes the CSVs as an easy-to-reference
record of extracted game sheets and an easy diffing view of changes during a
patch. Treat it as the source for static quest data and consult its commit history
when a patch changes a quest, sheet layout, NPC, map, or location.

English sheets are under `csv/en/`. Raw URL pattern:

```text
https://raw.githubusercontent.com/xivapi/ffxiv-datamining/master/csv/en/<Sheet>.csv
```

Useful sheets include:

- `Quest.csv` — quest metadata, script instructions, listeners, and todo data;
- `Level.csv` — world positions, object IDs, maps/territories, and radii;
- `ENpcResident.csv` — event NPC names;
- `EObjName.csv` — event-object names where applicable;
- `TerritoryType.csv`, `Map.csv`, `PlaceName.csv` — map and place context;
- item/action/content sheets referenced by non-talk objectives.

Pin or record the datamining commit used to generate a profile. A profile can
remain syntactically valid while becoming wrong after a game patch.

## Inspecting quest state in game

FFXIVMinion exposes a live `Quest` object and convenience globals. Given an
in-game quest ID:

```lua
local questId = 1208
return {
    id = questId,
    active = Quest:HasQuest(questId),
    complete = Quest:IsQuestCompleted(questId, false),
    step = Quest:GetQuestCurrentStep(questId, false),
}
```

Equivalent convenience calls commonly available in profiles are:

```lua
HasQuest(questId)
QuestCompleted(questId)
GetQuestInfo(questId, "step")
```

`Quest:GetQuestCurrentStep()` is the important runtime sequence value used to
verify which objective currently advances the quest. `255` is commonly used by
profiles/listeners for the final sequence, but completion should still be checked
with `QuestCompleted`/`IsQuestCompleted` rather than inferred only from a number.

To inspect the full runtime row when available:

```lua
local questId = 1208
local row = GetQuestByID(questId)
return {
    active = HasQuest(questId),
    complete = QuestCompleted(questId),
    step = GetQuestInfo(questId, "step"),
    row = row,
}
```

Return a cleaned subset if `row` contains userdata, functions, or a large nested
table. Never recursively stringify `_G` or other large/cyclic runtime tables.

## Resolving quest steps from datamined sheets

### Quest row IDs

For the observed quest data layout:

```text
Quest.csv row key = 65536 + in-game quest ID
```

Example:

```text
in-game quest 1208 → Quest.csv row 66744
```

The low 16 bits are the in-game quest ID. Verify this convention against the
current sheet/commit when tooling against a new patch.

### Actors and script instructions

Inspect `QuestParams[N].ScriptInstruction` and `.ScriptArg` in the quest row.
Common examples:

- `ACTOR0`, `ACTOR1`, ... — event NPC IDs; `ACTOR0` is normally the issuer;
- `RITEM0` — required item;
- `EMOTE0` — emote objective;
- instance/content instructions — duty or unlock objectives;
- `LOC_*`, `QUEST_*`, and other instructions — objective-specific data.

Do not assume every quest is a talk chain. Script instructions reveal item use,
emotes, combat, duties, unlocks, and other special steps.

### Listeners and sequences

`QuestListenerParams[N]` associates a listener with the quest sequences in which
it is active:

- `.Listener` — NPC or event-object ID that advances the quest;
- `.ActorSpawnSeq` / `.ActorDespawnSeq` — sequence range;
- sequence `255` commonly indicates the final hand-in stage.

Listeners are often close to objective order, but branching quests require
careful comparison of spawn/despawn/complete sequences. Validate the result in
game using `Quest:GetQuestCurrentStep(questId)`.

### Locations

`TodoParams[N].ToDoLocation[0]` references a row in `Level.csv`. Important Level
columns include:

```text
#, X, Y, Z, Yaw, Radius, Object, EventId, Map, Territory, Type
```

For profile authoring:

- `Object` normally becomes the step `id`;
- `Territory` normally becomes `mapid`;
- `X/Y/Z` become `pos`;
- event objects (often `2xxxxxx`) may require interaction behavior different from
  normal ENpcs.

If a todo location is absent, search `Level.csv` for the actor/object ID and the
expected territory. Existing profiles sometimes use a nearby reachable mesh
position instead of the exact Level coordinate, so small intentional offsets are
normal.

### Names

Resolve event NPC IDs through `ENpcResident.csv`. Resolve event objects through
appropriate EObj sheets. Use localized sheets when a profile needs localized
conversation text.

## Validation workflow

1. Record the game patch and `xivapi/ffxiv-datamining` commit.
2. Resolve the Quest row using `65536 + questId`.
3. Extract actors, listeners, sequences, todo locations, and non-talk script
   instructions.
4. Resolve Level coordinates/territory and NPC/object names.
5. Inspect the character live with the MCP bridge:
   `HasQuest`, `QuestCompleted`, and `Quest:GetQuestCurrentStep`.
6. Use reachable approach positions; do not blindly trust exact object centers.
7. Test one objective at a time. Verify the live sequence advances as expected.
8. Re-check special objectives: items, emotes, combat, duties, conversations,
   rewards, and branching paths.
9. On game patches, inspect the datamining repository diff and revalidate affected
   profiles.

## Caveats

- Listener order is a useful heuristic, not a proof for branching quests.
- Event-object interaction can differ from normal NPC interaction.
- Localized conversation text and indexes can differ by language.
- Never busy-wait for a quest, movement, UI, or interaction state in one MCP
  call; return current state and inspect it again later.
