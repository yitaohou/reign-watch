# What I would not ship

Things the design already makes impossible — spraying, unsourced sentences, an action without a record, an agent that sends — are the baseline, not the list. These five are what the system does not yet guarantee, and I would not put any of them in front of a bank until it does.

**1. The send step.** Wiring Gmail or a HubSpot sequence to "Approved" is an hour of work. I would not do it until a `message` record is written at send time, a "briefing booked" state exists for the CEO's rule, the recipient is a real person with consent on record (CASL), and approval means the approver read the brief. Today `send` is hard-coded false and `handoff.json` describes the record a send would need.

**2. This dashboard as the production approval surface.** "Acting as" is a dropdown, the audit log is an editable file, and `kill.json` is one shell command from gone. The approval *logic* is right; the identity and tamper-evidence under it are not there. It is a three-hour prototype and should be described as one.

**3. A brief whose citations were not checked against the source.** The eval proves every sentence carries a `[n]` and that the source is unchanged; it does not prove source *n* says what the sentence claims. The fan-out briefs for TD and CIBC were written by the agent and have not been read sentence-by-sentence against the text. In front of a CAE who has read footnote 3, cited-but-wrong is worse than uncited.

**4. A brief that invents the bank, or asks it to do something it must not.** Section 2 is where an agent under pressure to be specific will fabricate — a business line, a committee, a US entity. The ask has the mirror failure: "share your model inventory with us", "forward this to your regulator". The skill limits section 2 to the CRM record plus cited sources and forces conditional phrasing; nothing yet constrains what the ask may request.

**5. A list that shows only what the filter kept.** If the agent drops CIBC on a misread flag and all anyone sees is TD, the mistake is silent. The exclusions with their reasons *are* the audit of the filter. The check page shows every screened company today; the risk is any future view that simplifies it back to the winners.

