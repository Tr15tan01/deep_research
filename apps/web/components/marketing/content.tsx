import {
  BookMarked,
  Building2,
  Eye,
  FileStack,
  FlaskConical,
  GitBranch,
  History,
  LineChart,
  Lock,
  type LucideIcon,
  Microscope,
  PencilRuler,
  Quote,
  RefreshCcw,
  Scale,
  ServerCog,
  ShieldCheck,
  Swords,
  TriangleAlert,
  Upload,
} from "lucide-react";

export const FEATURES: { icon: LucideIcon; title: string; body: string }[] = [
  { icon: Quote, title: "Quotes are checked, not trusted", body: "The model must copy the exact passage that supports each claim. We search the retrieved page for it; if the passage isn't there, the claim is discarded and counted." },
  { icon: Eye, title: "Live view of the agent", body: "Watch the plan, each search query, every source it opens or rejects, and why — streamed from the server as it happens, not simulated." },
  { icon: PencilRuler, title: "Edit the plan first", body: "Review the sub-questions and queries before any searching starts. Add context, remove what's out of scope, then approve." },
  { icon: Scale, title: "Contradictions stay visible", body: "When sources disagree, the report presents each position with its own citations instead of averaging them away." },
  { icon: LineChart, title: "Charts only from verified numbers", body: "Data points become charts only when the number appears in a verified quote. Each bar or point opens its source." },
  { icon: TriangleAlert, title: "What is still unknown", body: "Every report lists open questions and the reason evidence was insufficient, so gaps are explicit." },
  { icon: Upload, title: "Research your own documents", body: "Upload PDF, DOCX, TXT or Markdown files and research them alone or alongside the web. Files are parsed in an isolated sandbox." },
  { icon: Swords, title: "Counterarguments and claim checks", body: "Ask for the strongest case against a report, or check a single claim for supporting and contradicting evidence." },
  { icon: RefreshCcw, title: "Regenerate one section", body: "Flag a wrong citation and rewrite just that section. Every change creates a new version you can compare." },
  { icon: History, title: "Reproducible by design", body: "Each report records the plan, queries, providers, model configuration, budgets and timestamps used to produce it." },
  { icon: FileStack, title: "Library and collections", body: "Save reports and sources, tag them, and see which past reports share sources with the one you're reading." },
  { icon: GitBranch, title: "Evidence graph", body: "See which sources support which findings, and where they conflict — every edge backed by a verified passage." },
];

export const USE_CASES: { icon: LucideIcon; title: string; body: string; example: string }[] = [
  { icon: Building2, title: "Vendor and product evaluation", body: "Compare options on price, features and limitations with a comparison matrix where every cell is cited or marked “not found”.", example: "Compare managed Postgres providers for a regulated EU workload" },
  { icon: Microscope, title: "Literature reviews", body: "Search scholarly indexes alongside the web. Abstract-only sources are labelled as such, never presented as full papers.", example: "What does recent research say about sleep and working memory?" },
  { icon: FlaskConical, title: "Technology decisions", body: "Weigh frameworks, architectures or approaches with evidence from documentation, benchmarks and post-mortems.", example: "Should a 5-person team choose server components or a SPA for an internal tool?" },
  { icon: BookMarked, title: "Market research", body: "Size markets and map players. Figures only become charts when the number is verified in a source.", example: "How large is the residential heat-pump market in Germany and who leads it?" },
  { icon: ShieldCheck, title: "Fact-checking", body: "Trace a claim to its origin and collect evidence on both sides before you repeat it.", example: "Is it true that most data breaches start with phishing?" },
];

export const SECURITY_POINTS: { icon: LucideIcon; title: string; body: string }[] = [
  { icon: Lock, title: "Your data stays yours", body: "Reports, sources and uploads are isolated per account and enforced on every query. You can export or delete everything at any time." },
  { icon: ServerCog, title: "No keys in the browser", body: "AI and search providers are called only from our servers. Provider keys are encrypted at rest and never sent to the client or written to logs." },
  { icon: ShieldCheck, title: "Hardened fetching", body: "Every page the agent fetches passes SSRF checks: private networks, metadata endpoints and DNS rebinding are blocked, and every redirect is re-validated." },
  { icon: TriangleAlert, title: "Prompt-injection aware", body: "Retrieved pages are treated as data, never instructions. Pages that try to instruct the AI are flagged in the report, and the model has no tools that can act on your behalf." },
];

export const FAQ: { q: string; a: React.ReactNode }[] = [
  { q: "How is this different from asking a chatbot?", a: "A chatbot answers from memory and may invent sources. Here, an agent searches, reads the actual pages, and keeps only claims whose supporting passage it can find in the retrieved text. Every citation in the report resolves to a stored source you can open." },
  { q: "Can the report still be wrong?", a: "Yes. Verification proves a quote exists in a source; it doesn't prove the source is right. That's why reports show source types (primary, secondary, commentary), publication dates, contradictions and an explicit list of unknowns. Treat reports as a strong starting point, not professional advice." },
  { q: "What does “evidence strength” mean?", a: "It's a transparent rule, not a probability: for example, “strong” means at least two independent domains including a primary source, with no contradicting evidence. The criteria are shown in every report." },
  { q: "Which AI models and search engines do you use?", a: "Administrators choose the exact provider and model (Google Gemini, OpenAI, Anthropic or an OpenAI-compatible endpoint) and the search providers (Firecrawl, Tavily, Brave, plus OpenAlex for scholarly search). Each report records which were used." },
  { q: "What happens if something fails mid-run?", a: "Runs are checkpointed after every step. Temporary provider outages are retried automatically; if a run stops, the verified findings gathered so far are kept as a clearly labelled partial report, and you can resume from the last checkpoint." },
  { q: "Do you train models on my documents?", a: "No. Uploaded documents are used only to answer your research and are deleted according to the retention period. Text you research is sent to the configured AI provider to process it; see the privacy policy for details." },
  { q: "How long does research take?", a: "Quick research usually takes one to three minutes; deep research can take up to half an hour. You can leave the page — the run continues on the server and you'll find it in your history." },
];
