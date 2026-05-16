If one pushes the categorical interpretation , the key step is to stop viewing semantic properties merely as edges in a graph and instead treat them as structure-preserving mappings between typed domains. In categorical language, many semantic properties behave more like functors between subcategories than individual morphisms.

A semantic wiki already has a rudimentary type system through categories. Suppose the wiki defines categories such as
	•	Theory
	•	Phenomenon
	•	Experiment
	•	Dataset
	•	Paper

Pages are objects in these typed collections. Let us denote these subcategories

\mathcal{T},\ \mathcal{P},\ \mathcal{E},\ \mathcal{D},\ \mathcal{L}

corresponding to theories, phenomena, experiments, datasets, and literature.

Now consider semantic properties like

explains
tests
measures
reports

Instead of treating these as arbitrary relations between pages, the agent interprets them as typed structure mappings.

For instance, the property

explains

maps objects in the theory domain to objects in the phenomenon domain. Formally:

F_{explains} : \mathcal{T} \rightarrow \mathcal{P}

Similarly,

F_{tests} : \mathcal{E} \rightarrow \mathcal{T}

and

F_{measures} : \mathcal{E} \rightarrow \mathcal{P}

These behave like functors because they preserve certain structural relations. For example, suppose two theories are related by refinement:

TheoryB extends TheoryA

If both theories explain the same phenomenon, the agent may infer that the explanation mapping respects that relation. In categorical terms, the explanation functor preserves morphisms that represent theoretical refinement.

Once properties are interpreted this way, the agent can reason about commuting diagrams.

Consider the diagram:

ExperimentE --tests--> TheoryT
ExperimentE --measures--> PhenomenonP
TheoryT --explains--> PhenomenonP

In categorical terms this suggests a triangle that should commute:

F_{explains}(F_{tests}(E)) = F_{measures}(E)

If the experiment tests a theory that explains a phenomenon, then the experiment should measure that phenomenon.

If the wiki contains

ExperimentE tests TheoryT
TheoryT explains PhenomenonP

but lacks

ExperimentE measures PhenomenonP

the agent detects a missing edge and proposes it.

In other words, diagram completion becomes a mechanism for knowledge discovery.

⸻

Another useful construction appears when two functors share the same codomain. Suppose both experiments and simulations map to theories they evaluate:

F_{tests} : \mathcal{E} \rightarrow \mathcal{T}

F_{simulates} : \mathcal{S} \rightarrow \mathcal{T}

where \mathcal{S} is a category of simulations.

The agent can construct a fiber product over theories. In practical terms this corresponds to identifying simulations and experiments that evaluate the same theory.

The resulting objects are pairs

(Simulation, Experiment)

linked by

targets same theory

From a research perspective this yields pages like

ValidationPair:SimulationX + ExperimentY

which represent empirical validation structures.

⸻

Adjunction-like relationships also arise naturally.

Consider the pair

theory explains phenomenon
experiment measures phenomenon

Theories move from conceptual structure toward observable predictions, while experiments move from observations toward theoretical evaluation. These can be interpreted as forming a loose adjoint relationship between the theory and experiment domains mediated by the phenomenon domain.

The agent can operationalize this by searching for unmatched pairs:

• phenomena predicted by theories but not measured by experiments
• experiments measuring phenomena not predicted by any theory

These correspond to gaps in the adjunction.

The agent then generates tasks such as:

Candidate theory needed for PhenomenonX

or

Experiment suggested for TheoryY prediction


⸻

This framework also interacts naturally with the graph export format used by RDF. RDF triples already encode subject–predicate–object relations. The agent simply groups predicates into typed families and interprets each family as defining a functor between object classes.

Thus the categorical structure is not stored explicitly in the wiki. It is inferred by the agent during graph analysis.

⸻

From an implementation standpoint the reasoning loop becomes:
	1.	retrieve triples from the wiki
	2.	partition pages by category (object types)
	3.	treat each property as a typed mapping between those types
	4.	construct diagrams implied by compositions
	5.	test whether diagrams commute
	6.	propose missing relations or new pages

Because the semantic wiki acts as persistent storage, every new relation added by the agent expands the structure available for future reasoning.

⸻

One unexpected consequence of this setup is that the wiki gradually accumulates higher-order conceptual structure. After enough pages exist, the agent can begin to detect patterns such as

• clusters of theories explaining the same phenomena
• chains of experiments refining earlier experiments
• datasets reused across unrelated projects

These correspond to recognizable categorical motifs such as cones, spans, and factorization patterns.

⸻

There is also a direction that aligns closely with your interest in compositional theories of cognition: constructing a category of theories themselves, where each theory page is an object and semantic properties describe mappings between conceptual frameworks.

