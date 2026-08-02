CONTEXT FOR AI APP — GROUPED STRUCTURE

01_Product_and_Functional_Design
Defines what the application does from the user's and product's perspective.

02_Engineering_Architecture
Defines the software layers, responsibilities, internal engines, repository shape, and runtime architecture.

03_Infrastructure_and_Data
Contains persistence, AI providers, embeddings, file indexing, configuration, and logging.

04_Service_and_Runtime
Contains the local API boundary, endpoints, and background worker processes.

05_Quality_and_Delivery
Contains testing strategy and the intentionally limited MVP scope and deployment shape.

## MVP governance for this planning collection

This collection is supporting historical/design material, not a source of MVP
authority. `SPECIFICATION_GOVERNANCE.md` defines its lower precedence. Any
conflict with root control documents must be resolved in favor of those root
documents before implementation.

For MVP, FastAPI/local APIs, cloud providers, model routing, streaming,
embeddings, vector stores, file indexing, background workers, cross-application
context, image/action execution, and automatic memory mutation are **Deferred
Post-MVP**. Arch Dock, Canva, Blender, Alienware, and desktop-dock examples are
historical fixtures only; they are not product defaults or required data.

The original source text was preserved except where an explicit MVP-status note
or contradiction correction was required.
