# Tone for serious grade / integrity notifications

User's corrections to a first draft (2026-09-24, E-Quiz 2 zero-out note to a student),
encoded as rules for this class of message. The owner (<Instructor-Name>) is precise about
what may and may not be asserted in a written student notification.

## Hard rules (from explicit correction)

- **Do NOT accuse** the student of dishonesty / not doing the work, **unless the
  evidence is paramount (decisive)**. Saying "the working suggests you didn't do it"
  from a soft signal (e.g. fewer recorded checks than in a sibling quiz) was rejected:
  "this is not a valid accusation as the evidence is not paramount." State the
  procedural fact (absent from the sampled-answer session → couldn't explain the
  working → zero per course policy) and stop there.
- **Do NOT call it a "repeated offence"** unless there is a documented prior
  incident. The owner explicitly retracted this ("I have not previously communicated
  with the student, so this is not a repeated offence"). Always check the student's
  prior quiz history / incidents before asserting repetition.
- **Do NOT list the most severe penalty (expulsion from the university)** unless the
  user explicitly asks for it. The owner removed the expulsion paragraph outright.
- **Do NOT demand "contact me immediately."** Instead, give a low-pressure,
  forward-looking instruction.

## What the message SHOULD contain (the approved shape)

1. Urgent framing of the grade consequence: the zero awarded and the procedural
   basis (absence from the in-class explanation sampling → unable to explain the
   submitted working → zero per course policy).
2. **The stakes, concretely:** "the E-Quiz grade constitutes a significant part of
   the continuous assessment; a zero here substantially reduces your final
   continuous-assessment component." (Factual, weight-driven — this is how urgency
   is conveyed, not by threats.)
3. A short, neutral academic-integrity reminder: "all work you submit must be your
   own, and you must be able to explain it when sampled." (One line — it's a
   reminder, not an accusation.)
4. **Forward-looking instruction:** attend the coming lectures; you are likely to be
   sampled for explanation again; attendance + ability to explain affect how answers
   are assessed.
5. Sign with the sender's real identity (see SKILL.md pitfall 1 on `userfrom`).

## Process

- **Verify every factual claim against the DB before sending** (grade value, scale,
  the specific check counts if mentioned, prior-incident history if any
  "repeated" language is even contemplated).
- Draft → show the owner → apply their corrections → deliver. Do not deliver a
  serious notification on the first draft.
- When evidence is mixed, prefer the milder, factual phrasing. The owner would
  rather understate than assert an unsupported finding in writing (it becomes part
  of a defensible audit trail).
