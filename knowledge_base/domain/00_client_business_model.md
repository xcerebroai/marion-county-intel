# 00 — Client Business Model

**This file is the foundation of the entire knowledge base. Every other rule, every score, every pattern, every review trigger exists to serve what is written here.**

---

## Who the operator is

The operator runs **Xcerebro LLC** and **AI Cheat Codes**. The operator builds **lead-generation systems for real estate investor clients**. The operator is not the end consumer of these leads. The clients are.

The operator's product is a system that pulls fresh county records daily, classifies and scores them, and delivers callable leads to the client's CRM (typically Go High Level). The client pays for the system because their existing data sources (PropStream, DealMachine, PropertyRadar) refresh monthly from bulk extracts and miss the freshness window where deals get won. The operator's edge is **daily refresh straight from county source**.

This means: the operator's reputation with clients depends on lead quality, not lead volume. A dashboard with 80 real sheriff sales is worth more than one with 7,000 records where 6,921 are noise. The framework must prefer honest empty buckets over inflated counts.

---

## Who the clients are — six personas

The framework must classify each lead so that the right client persona can act on it. A lead is not "good" or "bad" in the abstract. A lead is good *for a particular type of investor doing a particular type of deal*.

### 1. The Wholesaler

**What they do:** Find a property under contract at a discount. Assign the contract — or double-close — to a cash buyer for a fee ($5K–$50K typical). They do not own the property. They control it briefly.

**What they need from a lead:**
- A motivated seller (distress, urgency, or pain)
- Enough equity that a cash buyer can offer 70–80% of ARV minus repairs and still leave room for the wholesaler's fee
- A working contact path (phone, email, mailing address)
- A property type that has cash-buyer demand (most SFR, some small multi, light land)

**Lead patterns that fire wholesale candidate:**
- Tax delinquent + high equity
- Foreclosure pre-sale + absentee owner
- Probate + long-term ownership
- Code violation + entity owner
- Tired landlord (eviction history + multi-property)

### 2. The Flipper

**What they do:** Buy at a discount, renovate, resell at retail. They take title, take risk, take time (3–9 months typical).

**What they need from a lead:**
- Equity spread that survives ARV × 70% minus repairs minus carrying costs minus desired profit
- A property condition that's distressed but not condemned (cosmetic or moderate rehab is the sweet spot)
- A market with retail buyer demand
- Title path workable enough to close in 30–45 days

**Lead patterns that fire flip candidate:**
- Foreclosure + property condition issues
- Tax delinquent + cosmetic distress
- Estate sale + dated property
- Code violation (cosmetic/property maintenance, not condemnation)

### 3. The Subject-To Investor

**What they do:** Take title to a property *subject to* the existing mortgage staying in place. Seller deeds the property over; the original loan stays in the seller's name. Investor takes over payments, keeps any equity spread, holds or rents the property.

**What they need from a lead:**
- Seller behind on payments OR seller wanting out of debt
- A favorable existing loan (low rate, manageable payment, especially anything locked at sub-5% from 2020-2021)
- Property in livable or rentable condition
- Seller motivated by debt relief more than cash payout
- Often: foreclosure timeline creating urgency

**Lead patterns that fire subject-to candidate:**
- Foreclosure pre-sale (strongest signal)
- Mortgage arrears + low equity
- Recent payment-difficulty signals (NSF, missed-payment liens)
- Divorce with property + payment pressure

### 4. The Seller-Finance Investor

**What they do:** Buy with the seller acting as the bank. Buyer pays a down payment and makes monthly payments to the seller for a term (5–30 years), often with a balloon. Seller gets monthly income; buyer gets the property without bank financing.

**What they need from a lead:**
- Free-and-clear or near-free-and-clear property
- Long-term owner (15+ years often correlates with paid-off)
- Seller motivated by income or tax reasons more than cash
- Often: retiring landlord, estate-owner who inherited, owner who wants out but doesn't want a tax hit

**Lead patterns that fire seller-finance candidate:**
- Long-term-owned + free-and-clear + tired-landlord signals
- Estate-owned + multiple-properties owner
- Senior owner + low last-sale-price (often paid off generations ago)

### 5. The Partial-Interest Investor

**What they do:** Buy out one or more co-owners of a property where multiple parties hold fractional interest. Then either negotiate with remaining owners, file partition, or hold and force a sale. Specialist work — most investors won't touch it.

**What they need from a lead:**
- Multiple owners on record
- Often: probate without complete distribution, divorce without partition, tenancy-in-common, family inheritance disputes
- One or more owners willing to sell their share at a discount
- A property valuable enough to justify the legal work

**Lead patterns that fire partial-interest candidate:**
- Probate case + multiple heirs
- Affidavit of heirship + tax delinquent
- Quiet title case
- Partition lawsuit
- Deed with fractional consideration

### 6. The Messy-Title Investor

**What they do:** Specialize in properties with title problems most investors avoid — old liens, judgment clouds, unreleased mortgages, missing heirs, deed gaps. Resolve the title issue, then sell or hold. High margin, slow timeline.

**What they need from a lead:**
- A title cloud that scares retail buyers
- A motivated owner who can't sell because of the cloud
- A title issue that's resolvable (curative, not catastrophic)

**Lead patterns that fire messy-title candidate:**
- Multiple liens + long-term ownership (often unreleased)
- Probate without distribution
- Judgment lien + low-equity property
- Quiet title pending
- Deed-gap signals (chain of title break)

---

## How the framework serves these personas

Every output of the framework — every dashboard chip, every CSV column, every CRM tag, every score — exists so the operator's client (one of the six personas above) can sort the dashboard, pick the leads relevant to their deal type, and start calling. This means:

1. **Every lead must have at least one suggested deal path.** A lead with no deal path classification is incomplete. Send it to review.

2. **Every score must have reasons.** "Wholesale candidate, 78/100" is useless to a wholesaler. "Wholesale candidate, 78/100 — high equity proxy, absentee mailing out-of-state, sheriff sale 14 days out" is callable.

3. **Every dashboard view must be sortable by deal path.** A wholesaler shouldn't have to wade through messy-title leads to find their list.

4. **Every lead must have a callable contact path.** Phone or mailing address minimum. If neither exists, the lead is incomplete. Send to skip-trace queue, not dashboard.

5. **Every lead must have a verifiable source URL.** When the client asks "where did this come from?", the operator must be able to point to a county-clerk page, a court docket, a tax assessor record. Leads without source URLs are unsupported and do not export.

---

## What this knowledge base is not

This knowledge base does not include:
- Specific scripts or talk tracks for calling sellers (operator and clients handle that)
- Pricing models for the operator's lead-gen service (business decision, not framework decision)
- Skip-trace vendor selection (operator decision)
- CRM workflow design (handled in the client's GHL setup, downstream of this framework)
- Legal advice on any deal structure (the framework flags candidates, attorneys handle execution)

The framework's job is to surface clean, scored, classified, callable leads. What happens after the call is the client's business.

---

## The Infranodus knowledge graph context

The operator maintains a `real_estate_wholesale_knowledge_graph` in Infranodus that maps the wholesaling domain into six clusters: Property Sourcing, Lead Management, Deal Analysis, Buyers & Sellers, Marketing & Outreach, Contracts & Closing. The framework's lead-types and deal-path classifications are the **Property Sourcing** and **Lead Management** layers of that graph — the part that's missing from public knowledge graphs because most lead-gen content stops at "use PropStream" and starts the conversation downstream.

The framework does not consume the Infranodus graph at runtime. The graph exists to remind the AI that everything upstream serves a wholesaling business that has many other parts (deal analysis, contracts, closing, dispo) which depend on lead quality. **Bad leads break the entire chain.**
