# Suggest a Purchase: Digital Self-Service for CHPL Customers

*Connecting people with the world of ideas and information*

---

## Customer Impact

CHPL customers can now suggest purchases from any device, 24/7. No forms to mail, no emails to write, no waiting for staff availability. Customers describe what they want in plain English, submit their request, and track its status in real-time—all from their phone, tablet, or computer.

This directly supports CHPL's mission of **connecting people with the world of ideas and information** by removing barriers between customers and the materials they need.

---

## What This Means for Customers

### Easy Access

Sign in with your library card number and PIN—the same credentials used for other CHPL services. No new accounts to create.

![Customer Login](screenshots/patron_login.png)

### Submit in Plain English

Customers don't need to know ISBNs, exact titles, or author spellings. They simply describe what they're looking for:

> "The new mystery by Louise Penny that just came out"
> "A book about learning guitar for beginners"
> "The audiobook of Project Hail Mary"

![Submission Form](screenshots/patron_form.png)

### Any Format

Books, eBooks, audiobooks, DVDs, music—customers can request any format and note their preferences.

### Transparency

Customers see their request status update as it moves through the process:

- **New** — Request received
- **In Review** — Staff is evaluating
- **Ordered** — On its way to the collection
- **Declined** — With explanation

No more wondering "did they get my request?" or "what happened to it?"

![My Requests](screenshots/patron_my_requests.png)

### Responsive Service

Automated processing means staff can focus on collection development decisions rather than data entry, resulting in faster turnaround for customers.

---

## What This Means for Staff

### Automated Research

The "suggest-a-bot" processor automatically:

- **Extracts identifiers** — Finds ISBNs, DOIs, and URLs in customer requests
- **Checks the catalog** — Searches Sierra to identify duplicates or existing holdings
- **Enriches metadata** — Looks up authoritative information from Open Library

Before staff even sees a request, the system has already gathered the research needed to make a decision.

![Staff View](screenshots/staff_table.png)

### Focus on Decisions

Staff spend time on **collection development decisions**, not data entry:

- Is this title appropriate for our collection?
- Do we need another copy?
- Should we purchase in multiple formats?

### Full Audit Trail

Every action is tracked—who changed what, and when. This supports accountability and helps identify patterns in customer requests.

### Reporting

Export requests to CSV for analysis, reporting, or integration with other systems.

---

## How It Was Built: Innovation in Action

This system demonstrates CHPL's commitment to **continuous learning and innovation** as "a dynamic force" in the community.

### AI Pair Programming

The Suggest a Purchase system was developed using **AI pair programming** with Claude Code—a collaborative approach where human expertise guides AI-accelerated implementation.

> **"We believe we go farther, together."**
>
> This CHPL belief directly describes our development approach: human expertise setting direction, reviewing decisions, and ensuring quality—combined with AI acceleration that turns well-defined requirements into working software rapidly.

### The Key Insight

**Well-defined requirements enable rapid iteration.**

Before any code was written, clear design documents established:

- What customers need
- How staff will use the system
- Integration points with Sierra ILS
- Security and privacy requirements

With these foundations in place, AI pair programming transformed days of work into hours.

---

## Timeline: One Day of Development

```text
2026-01-24: Design to Working System
═══════════════════════════════════════════════════════════════════

MORNING — Foundation
├── Initial system with Sierra ILS authentication
├── Customer login, submission, and status tracking
└── Core database schema and API routes

MIDDAY — Infrastructure
├── Automated testing pipeline (CI/CD)
├── Security review and hardening
└── Configuration management

AFTERNOON — Automation (Bot M1-M2)
├── ISBN/ISSN/DOI extraction from customer requests
├── Automatic Sierra catalog lookup
└── Duplicate detection

EVENING — Enrichment (Bot M3)
├── Open Library integration
├── Metadata enrichment for items not in catalog
└── Documentation and testing

═══════════════════════════════════════════════════════════════════
RESULT: 321 automated tests passing, production-ready proof of concept
```

### 22 Commits in One Day

From initial design review to a working system with:

- Customer-facing submission and tracking
- Staff review interface
- Automated research pipeline
- Comprehensive test coverage

---

## Technical Quality

### Built on Trusted Foundations

**Datasette** — Used by Reuters, The Guardian, and data journalists worldwide for reliable data publishing. Created by Simon Willison, a well-known figure in the Python and open data community.

**Sierra ILS Integration** — Uses your existing Sierra authentication. Customers log in with their library card; the system verifies credentials against Sierra in real-time.

### Designed for Reliability

- **321 automated tests** verify the system works correctly
- **Database migrations** ensure safe upgrades
- **Audit logging** tracks all changes
- **Error handling** prevents data loss

### Designed for CHPL

The system is built specifically for CHPL workflows, not a generic "one size fits all" product. It can be customized as needs evolve.

---

## Next Steps

### Near-Term Enhancements

**Smarter Input Understanding (M4)**

Use AI to better interpret customer requests:

- "The sequel to that dragon book" → identifies the series and next title
- Handles misspellings, incomplete information, and vague descriptions

**Consortium Availability**
Check OhioLINK and SearchOhio to see if requested items are available for interlibrary loan—giving staff more options when making decisions.

### Production Pilot

1. Deploy to CHPL infrastructure
2. Test with a small group of staff and customers
3. Gather feedback and iterate
4. Expand to full production

---

## Why This Approach Matters

### Rapid Response to Customer Needs

AI-assisted development enables CHPL to respond quickly when customers need new services. Instead of months-long projects, well-defined requirements can become working software in days.

### Iterative Improvement

The system can evolve based on real customer and staff feedback. Small improvements ship quickly; there's no need to wait for "version 2.0."

### CHPL as a Dynamic Force

This project demonstrates what's possible when a library embraces innovation:

> **Customer Focus:** "Responsiveness to patron needs" — customers asked for an easier way to suggest purchases; this delivers it.
>
> **Access:** "Free, open, unrestricted access" — no special knowledge required; describe what you want in your own words.
>
> **Innovation:** "Continuous learning and innovation" — AI pair programming is a new capability that accelerates service delivery.
>
> **Connection:** "We go farther, together" — human expertise + AI collaboration = faster results for customers.

---

## Summary

The Suggest a Purchase system transforms how CHPL customers request materials:

| Before | After |
| ------ | ----- |
| Mail forms, email, or wait for staff availability | Submit anytime from any device |
| Wonder if request was received | Track status in real-time |
| Staff manually researches each request | Automated catalog lookup and metadata enrichment |
| Days to process | Faster turnaround |

Built in one day using AI pair programming, this proof of concept demonstrates how CHPL can deliver responsive, customer-focused digital services rapidly—embodying the library's mission of **connecting people with the world of ideas and information**.

---

*Developed with Claude Code — AI pair programming for rapid, quality software development*
