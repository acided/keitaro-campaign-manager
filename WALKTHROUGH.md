# Walkthrough

How the task was read, the decisions behind the code, edge cases, and what I would ask before taking this further.

## 1. How I read the task

- **"The numbers must be right"** is the core requirement, so all weight and state logic lives in one
  pure module (`backend/app/editor.py`) with no I/O, and it is covered by tests before anything else.
  The frontend has no weight logic at all: every action returns the whole stream and the UI just re-renders it.
- **The Keitaro instance is shared production.** It holds hundreds of campaigns, many of them other candidates'
  `test_*` ones. So the app is fenced to campaigns named `test_kochkurov_*` (configurable), and nothing ever
  reads streams of, or writes to, anything else.
- **Before writing code I probed the API** on a throwaway campaign of my own, to replace assumptions with facts:

  | Question | Answer from the live instance | Consequence |
  |---|---|---|
  | Does `PUT /streams/{id}` with `offers` merge or replace? | Replaces the whole list | Push is one PUT with the full list of active offers; removing = leaving it out |
  | Does Keitaro check that shares sum to 100? | No, 50 + 30 = 80 is accepted | We validate before Push |
  | Where does the redirect URL go? | `action_payload`, not `action_options` | Used in the creator |
  | Is offer order in responses stable? | No | UI order is stored locally |
  | Does Cloudflare block library User-Agents? | Yes, `Python-urllib` gets 403 | The client sends an honest `keitaro-campaign-manager/0.1` UA |

## 2. Data model: two layers per offer

Each `stream_offers` row stores the offer twice:

- **published**: `pub_state`, `pub_share`, `pub_pin`. What Keitaro has now; `pub_state = NULL` means "never published".
- **draft**: `state`, `share`, `pin`. What the user sees and edits.

A stream is **yellow** when any row's draft differs from its published layer. Everything else follows from that:

| Action | Draft | Rebalance | Stream after |
|---|---|---|---|
| Add | new row, published layer empty | yes | yellow |
| Remove | `removed`, share 0, pin kept; a never-published row is deleted instead | yes | yellow unless it matches published |
| Bring back | `active`, share = pin or from rebalance | yes | yellow, or white if everything is back |
| Pin / Unpin | `pin := value` / `NULL` | yes | yellow if anything changed |
| Push | published := draft | no | white |
| Cancel | draft := published, never-published rows deleted | no | white |
| Fetch | published layer refreshed from Keitaro | no | unchanged |

**Why two layers instead of re-reading Keitaro on Cancel:** pins exist only in our database, and removed
offers have to stay visible as grey rows after Keitaro forgot them. Neither can be recovered from Keitaro,
so the last published state has to live here. The pin is part of the layer: otherwise Cancel would restore
the weights but keep a pin, and the numbers would disagree.

**Why `pin` is a value, not a flag:** a removed offer has share 0 but must come back with its old weight
(as in the video), so the pinned weight is stored separately from the current share.

## 3. Weights

`rebalance()`: removed offers get 0, pinned active offers get exactly their pin, and the remaining
`100 - sum(pins)` is split evenly between unpinned active offers in whole percent with the largest remainder
method. All remainders are equal in an even split, so the leftover points go to the first offers in UI order:
3 offers are 34/33/33, never 33/33/33 = 99.

The end-to-end example is a test, through the pure functions and through HTTP:
`34/33/33 → Add → 25/25/25/25 → Pin first at 40 → 40/20/20/20 → Remove second → 40/0/30/30 → Bring back → 40/20/20/20 → Cancel → 34/33/33`.

## 4. Fetch and sync with Keitaro

- An offer in Keitaro but not here is added with Keitaro's weight.
- An offer published here as active but missing in Keitaro becomes **removed** (grey, with Bring back),
  exactly as if it had been removed here. An offer with `state: disabled` in Keitaro is shown the same way.
- Weights from Keitaro are taken as they are: Fetch never rebalances, because the wrapper should not
  change anything without a user action. If they do not sum to 100, Push stays blocked until the user acts.
- Fetch always refreshes the published layer. A white stream also gets its draft reset to it. A **yellow stream
  keeps its draft**, and the yellow diff is now computed against the fresh Keitaro state, so no user work is
  lost. The task does not say what should happen here, see the questions below.
- Pins live only here, Fetch never touches them.

## 5. Creator

- Geo accepts `mx, AU ro;MX`: any separators and case, duplicates dropped, checked against ISO 3166-1 alpha-2.
- The `test_kochkurov_` prefix is added when missing; the alias is a URL-safe slug plus a random suffix.
- Name, geo and offer are validated **before** the first Keitaro request, so bad input never creates anything.
- Creation is three requests (campaign, stream 1, stream 2). If a stream fails, the campaign is deleted, so no
  half-created campaign is left in the shared Keitaro. If that delete fails too, the error says which id to delete.
- Domain, group and traffic source are dropdowns; `FORTESTS` is preselected. The domain from the task
  screenshot (`in.posdk.xyz`) is not visible to this API key, so the first available domain is the default.
- After creation the campaign opens in the editor straight away.

## 6. Edge cases

| Case | Behaviour |
|---|---|
| Pins would sum to more than 100 | Pin / Bring back refused with 422 and a message |
| All active offers pinned, sum ≠ 100 | Push blocked, reason shown on the stream |
| Pins sum to exactly 100 with unpinned offers present | Allowed, unpinned offers get 0% |
| No active offers left | Push blocked |
| Add an offer that was removed | 409 "use Bring back", so the pin and history are kept |
| Remove an offer that was never published | Row is deleted, not greyed out |
| Push fails in Keitaro | Nothing changes locally, stream stays yellow, error shown |
| Push accepted by Keitaro, local commit fails | Next Fetch reconciles (Keitaro is the source of truth) |
| Stream deleted in Keitaro | Deleted locally on the next Fetch |
| Stream without offers (redirect) | Shown as a plain stream without an editor |
| Campaign of someone else | 403 before its streams are read |

## 7. Questions for the CTO

1. **Fetch on a yellow stream.** I keep the draft and recompute the diff against fresh Keitaro data. The
   alternative is "Fetch = Cancel + refresh". Which matches how the team works?
2. **Disabled offers.** An offer someone set to `disabled` directly in Keitaro is shown as removed here, and the
   next Push drops it from the stream, because Push sends only active offers. Should Push keep it in Keitaro as
   `disabled` instead?
3. **Pinned offer edited directly in Keitaro.** If someone changes a pinned offer from 25 to 30 in Keitaro,
   Fetch shows 30 and keeps the pin at 25; the next action returns it to 25. Should Fetch drop such a pin?
4. **Concurrent changes.** Push overwrites whatever is in Keitaro at that moment. A check that the stream has not
   changed since the last Fetch (comparing `updated_at`) would prevent overwriting a colleague's edit. Worth it?
5. **Stream 2 type.** It is a `regular` stream without filters at position 2, which catches everyone stream 1 did
   not. Keitaro also has a `default` stream type for "everyone else". Is there a team convention?
6. **Users and access.** There is no authentication: the app assumes a trusted internal network. Who would use it?

## 8. What is not done

- No authentication or audit log of who pushed what.
- No optimistic-concurrency check before Push (question 4).
- Frontend has no automated tests; the backend has 75 tests, and the whole scenario was run once against the
  live Keitaro (23 checks, each verified by reading Keitaro back directly).
- `GET /campaigns` loads all campaigns and filters by prefix: fine for hundreds, not for very large instances.
- The offer catalog is cached in process memory for 2 minutes, which is fine for one API instance only.
- No CI pipeline.

## 9. Likely questions

**Why keep business logic out of the endpoints?**
`editor.py` is pure functions over a list of rows, so every rule is tested in milliseconds without a database
or HTTP, and endpoints are thin: load the stream, call one function, commit, return the view.

**Why not compute "dirty" by comparing with Keitaro live?**
It would need a Keitaro call on every render, and it still could not represent pins or removed offers,
which Keitaro does not store.

**Why is Push one PUT with the full list?**
The probe showed that Keitaro replaces the list, so a partial update is impossible anyway. One request also
means the stream is never half-published.

**What happens if two people edit the same stream?**
Both edit the same draft in our database (last write wins per action); the unique `(stream_id, offer_id)`
constraint prevents duplicate rows. Against Keitaro, Push overwrites; see question 4.

**Why are campaign and stream ids the Keitaro ids?**
The database only mirrors Keitaro entities. Using their ids removes a mapping layer and makes URLs match Keitaro.

**How do you make sure the app never touches other campaigns?**
The prefix is checked when a campaign is created and when it is fetched, before reading its streams. Streams only
get into the database through Fetch, so every stream action is limited to our campaigns. A test asserts that
fetching a foreign campaign never reads its streams.

**Why largest remainder?**
Shares in Keitaro are whole percent. Rounding each share separately gives 33/33/33 = 99; largest remainder
always sums to exactly 100 and never differs between offers by more than 1.
