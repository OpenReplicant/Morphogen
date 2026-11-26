# Paper ingestion: parser survey (checked 2026-11-25)

Scope: converting papers (mostly arXiv, plus publisher PDFs and web pages) to Markdown with a sidecar that maps spans back to source positions, so every extracted claim cites a span that can be checked mechanically. Versions, dates and licences below come from the GitHub API, PyPI JSON and Hugging Face model APIs and cards, all fetched today. Speed and accuracy figures are taken from the projects' own docs and are self-reported unless I say otherwise. Nothing was installed or run.

Legend: **[V]** verified from a primary source today. **[U]** unverified or inferred: check it before relying on it.

## Comparison table

| Project | Latest version (date) | Code licence | Weights licence (what it downloads) | Provenance output | Tables | Formulas | CPU speed (reported) | MCP server |
|---|---|---|---|---|---|---|---|---|
| **Docling** (IBM / LF AI, `docling-project/docling`) | v2.153.0 (2026-11-25) [V] | MIT [V] | Layout: `docling-layout-heron`/`egret-*` Apache-2.0. Tables: `TableFormerV2` Apache-2.0, `docling-models` CDLA-Permissive-2.0 + Apache-2.0. Formula/code: `CodeFormulaV2` CDLA-Permissive-2.0 (`CodeFormula` v1 MIT). Optional VLM `granite-docling-258M` Apache-2.0. OCR engine is your choice (EasyOCR/RapidOCR/Tesseract extras) [V] | Lossless JSON (`DoclingDocument`). Each item has a JSON-pointer `self_ref` (e.g. `#/texts/12`) and `prov[]` = page_no + bbox (+ charspan). Table cells carry bbox, row/col span and start/end row/col offsets. Reading order and section hierarchy are kept [V]. Markdown export does not carry the mapping inline, so you build the sidecar from the JSON [U: the mechanics are a design step] | TableFormer cell structure, exported as HTML/Markdown, with cell bboxes [V] | `do_formula_enrichment` (off by default) gives LaTeX via CodeFormulaV2 [V] | Tech report (self, 2024 version, OCR off): 1.27-2.45 pg/s on M3 Max, 0.60-1.57 pg/s on a Xeon E5-2690, 16 cores. Datalab's benchmark (competitor) puts docling at 1.4 pg/s on CPU. EasyOCR on CPU is ">30 s/page" (self) [V] | **First-party `docling-mcp`** v3.5.1 (2026-11-23), MIT, stdio/SSE/HTTP via `uvx`. Also `docling-serve` 1.39.0 (REST) [V] |
| **Unstructured** (open-source lib) | 0.27.38 (2026-11-24) [V] | Apache-2.0 [V] | `hi_res` default layout model `unstructuredio/yolo_x_layout`: LICENSE.txt is Apache-2.0 (no HF licence tag). Tables: `microsoft/table-transformer-structure-recognition` MIT [V] | Element list. Each element has `element_id`, `parent_id`, `category_depth`, `page_number`, `coordinates` (points + system) and `detection_class_prob` [V] | `text_as_html` plus `table_as_cells` on Table elements [V]. Quality depends on strategy (`fast` vs `hi_res`) [U] | A `Formula` element type exists. No LaTeX recognition in the OSS lib [U] | Not reported for the OSS lib [U] | `UNS-MCP` is for the **hosted API** and is marked "not actively maintained". The hosted "Transform MCP" is a paid service. No local OSS MCP [V] |
| **MarkItDown** (Microsoft) | v0.1.9 (2026-10-21) [V] | MIT [V] | None by default (pdfminer.six + pdfplumber). OCR plugin calls an LLM you supply. Optional Azure Document Intelligence (cloud) [V] | **None.** Plain Markdown, no page or bbox mapping [V] | pdfplumber tables flattened to Markdown [V] | None [U] | Fast (text layer only). No figure published [U] | **First-party `markitdown-mcp`** 0.0.1a8 (2026-10-21), MIT, one tool `convert_to_markdown(uri)` [V] |
| **Marker** (Datalab) | v2.2.0 (2026-11-12) [V] | Apache-2.0 [V] | **Modified AI Pubs OpenRAIL-M**: free for research, personal use and startups under $5M funding/revenue. Commercial use above that needs a paid licence. This covers Surya 2.5 VLM, Indra ONNX (`license_name: datalab-openrail-m`) and the layout models [V] | JSON tree. Block ids like `/page/10/Table/9`, a 4-corner polygon per block, `section_hierarchy`, and a flat "chunks" format [V] | HTML `<table>` blocks with page bboxes in JSON [V] | LaTeX (`$$` in MD, `<math>` in HTML). Inline math via OCR in balanced mode, or with `--ocr_inline_math` in fast mode [V] | Self (OmniParseBench): `fast` 23.6 pg/s CPU (score 71.0), `no_ocr` 57 pg/s CPU (40.8 overall; 81-83 on born-digital) [V, self-reported] | No first-party MCP. Only small third-party repos (e.g. `Rlahuerta/marker-mcp`, 0 stars) [V] |
| **MinerU** (OpenDataLab / Shanghai AI Lab) | 4.2.3 (2026-11-16) [V] | **"MinerU Open Source License"**: Apache-2.0 plus extra terms: a separate commercial licence is needed above 100M MAU or USD 20M monthly revenue, online services must show attribution, and rights terminate on breach. Not OSI-approved. Was AGPL in earlier versions [V] | `MinerU-4_models_torch` bundle (PP-DocLayoutV2, PP-OCRv6, PP-FormulaNet+, SLANet+) is tagged Apache-2.0, "original models retain their respective licenses". `MinerU2.5-Pro-2605-1.2B` VLM Apache-2.0. **Older `MinerU2.5-2509-1.2B` is AGPL-3.0.** The ONNX bundle has no licence tag [V; per-component licences of the Paddle models U] | `content_list`/`middle_json` with zero-based `page_idx`, blocks with bboxes, page sizes in pt. 4.x adds "stable citation locators" (`doc:<id>/tier:standard/page:N/block:M`) [V] | Ruled and borderless table models, HTML output, cross-page table merging (4.2) [V] | LaTeX via PP-FormulaNet (basic) or VLM (standard/advanced) [V] | `basic` tier runs on CPU via ONNX (~0.8 GB models, 2 GB RAM). `standard` works on CPU with llama.cpp but Vulkan is recommended. No CPU pg/s figure in the README. Datalab (competitor) reports MinerU 2.5-Pro at 0.54 pg/s on GPU [V] | `mineru-mcp` 1.0.0 on PyPI (2025-06-09, MIT), a wrapper for the MinerU **API** with a local option, predating 4.x. MinerU 4 ships an agent "skill" plus a CLI document library, but no MCP [V; 4.x compatibility of mineru-mcp U] |
| **GROBID** (now `grobidOrg/grobid`) | 0.9.1 (2026-08-04) [V] | Apache-2.0. Bundles **pdfalto, GPL-2.0**, run as a separate native binary [V] | Default models are CRF (Apache, shipped). Optional DeLFT deep-learning models (Apache-2.0 code). Model files ship with the repo/Docker [U for the exact weight licence text] | TEI XML with `coords` (page,x,y,w,h) on requested elements: paragraphs, sentences, figures, refs, formulas. Structured header, sections, citations and references (best in class for references: ~0.87-0.90 F1, self) [V] | Detects table zones and gives a TEI table. Cell structure is weak in practice [U] | Detects and locates formula zones. **No LaTeX** [U] | Self: 10.6 PDF/s on one 16-CPU machine, CRF, full text (2019 issue) [V, self-reported] | No first-party MCP. Third-party `JackKuo666/grobid-MCP-Server` (stale, 2025-03) [V] |
| **Nougat** (Meta) | 0.1.0-base (GitHub 2023-08-22). PyPI `nougat-ocr` 0.1.17 (2023-10-04). Last push 2025-02 [V] | MIT [V] | **`facebook/nougat-base`: CC-BY-NC-4.0 (non-commercial)** [V] | None (page-level Markdown/MMD, no bboxes) [V] | LaTeX tables, often hallucinated on hard pages [U] | LaTeX (its strength) [V] | GPU-oriented, very slow on CPU [U] | None found |
| **PyMuPDF4LLM** (Artifex) | Merged into **PyMuPDF 2.x**. `pymupdf` 2.1 (2026-11-02). `pymupdf4llm`/`pymupdf-layout` 2.1 are now empty shims. GitHub `pymupdf4llm` last tag v0.3.4 (2026-02-14) [V] | **AGPL-3.0 or Artifex commercial** (pymupdf, pymupdf4llm, pymupdf-layout) [V] | PyMuPDF Layout GNN (ONNX) under the same AGPL/commercial dual licence [V] | `to_markdown`/`to_json`. Page chunks with page metadata and table/image boxes [U: exact JSON schema not checked] | Native table finder to Markdown [U] | No LaTeX recognition [U] | Fast on CPU ("10x the speed", self, no figure) [V, self] | `pymupdf4llm-mcp` 1.28.0 on PyPI (2026-07-02). Repo link 404s today [V/U] |
| *Also current:* **olmOCR** (AllenAI) | v0.4.27 (2026-03-12) [V] | Apache-2.0 [V] | `olmOCR-2-7B-1025` Apache-2.0 [V] | Page-level text only, no bboxes [U] | Good (olmOCR-bench) | Good | 7B VLM, needs a GPU; not practical on CPU [U] | None first-party |
| *Source route:* **arXiv HTML** (LaTeXML / latexml-oxide) | arXiv now generates with **latexml-oxide 0.7.6** (Rust port, release 2026-08-23). Perl LaTeXML v0.8.8 (2024-02) [V] | latexml-oxide CC0-1.0. LaTeXML public domain (NIST) [V] | None | Stable element ids for sections, paragraphs, tables and maths (`S1.p2`, `S4.T1`, `S1.p2.m1`). **No page numbers or bboxes.** Only `ltx_pagination` markers [V] | Real `<table class="ltx_tabular">` from the author's LaTeX [V] | MathML with TeX in the `alttext` attribute (142 equations in 1706.03762) [V] | Pre-rendered. Fetching costs nothing to compute | n/a |

## Benchmarks found (none fully independent)

- **OmniDocBench v1.6** (`opendatalab/OmniDocBench`, the MinerU team, so MinerU rows are effectively self-reported). Overall = mean of (1-text edit)x100, table TEDS and formula CDM. Overall / Table TEDS / Formula CDM: MinerU2.5-Pro 95.75 / 93.42 / 97.45; MinerU-Pipeline 3.4.0 86.47 / 81.88 / 83.07; olmOCR 85.74 / 83.00 / 88.10; Marker 78.44 / 65.77 / 85.24 (Marker version not shown in the v1.6 table). PaddleOCR-VL-1.6 tops it at 96.34. Docling appears only in older v1.0 component tables.
- **olmOCR-bench** (AllenAI, who make olmOCR; self-interested). Overall: olmOCR v0.4.0 82.4, Marker 1.10.1 76.1 (arXiv split 83.8, tables 72.9), MinerU 2.5.4 75.2 (arXiv 76.6, tables 84.9). No Docling, GROBID or Unstructured rows.
- **OmniParseBench** (Datalab, the Marker maker; self-reported, and run by a competitor for the other rows). Marker fast 71.0 at 23.6 pg/s on CPU. docling 67.5 (tables 72.0, higher than Marker fast's 59.6) at 2.1 pg/s GPU / 1.4 pg/s CPU. Marker balanced 80.5.
- **Docling Technical Report** (arXiv 2408.09869, self-reported, 2024 pipeline): CPU throughput above.
- **GROBID docs** (self-reported): reference parsing F1 ~0.87-0.90, end-to-end benchmarks on readthedocs.
- I found no independent, peer-reviewed comparison that covers Docling, Marker, MinerU and GROBID together on scientific PDFs with current versions. **[U]**

## Recommendation

**(a) Default PDF parser: Docling.**
- It is the only candidate where every licence is permissive and approved: MIT code, Apache-2.0 / CDLA-Permissive-2.0 weights. That matters for a kit other people install.
- Its native output already has the provenance we need: JSON-pointer ids, page number, bbox and charspan per item, and table cells with row/col offsets and bboxes. The Markdown-plus-sidecar can be generated straight from `DoclingDocument`.
- It handles reading order and has optional LaTeX formulas (turn `do_formula_enrichment` on).
- It has a maintained first-party MCP server.
- It also reads LaTeX, HTML and JATS XML, so the same document model covers the source route and publisher XML.
- Costs: about 1-2.5 pg/s on CPU with OCR off (self-reported, 2024). Run born-digital PDFs with `do_ocr=False` and enable OCR only for scans.

**(b) Fallbacks, chosen by failure mode:**
- **MinerU 4.x (basic/standard tiers)** for formula-dense or scanned pages, or when Docling's tables score low. It tops OmniDocBench, but that is a self-published benchmark, and it keeps page_idx and bbox locators. Before shipping it: its licence is Apache-2.0 plus a revenue/MAU threshold and an attribution clause (not OSI), and some older VLM weights (MinerU2.5-2509) are AGPL. Pin the Apache-tagged `MinerU-4_models_*` and `MinerU2.5-Pro` weights.
- **GROBID** as a complement rather than a replacement: header metadata, section structure and especially bibliography/citation linking, with TEI coordinates. CRF mode is fast on CPU. Run it as a Docker service because pdfalto is GPL-2.0 (separate process, so no linking).
- **Avoid for redistribution:** Marker/Surya (OpenRAIL-M weights with a $5M commercial cap, even though it is the fastest CPU option), PyMuPDF4LLM (AGPL), Nougat (CC-BY-NC weights, unmaintained since 2023). MarkItDown is fine for web pages and office files but gives **no provenance** for PDFs. Unstructured is permissive with decent element coordinates, but it has no formula LaTeX and its MCP is a hosted API, so it is a reasonable second choice only if Docling fails to install.

**(c) When to prefer arXiv HTML or LaTeX over the PDF:**
- **arXiv HTML first for any arXiv paper that has it.** HTML exists for new submissions plus a backfill of the older corpus. latexml-oxide self-reports 98% error-free conversion.
- It wins on fidelity: tables and numbers come from the author's LaTeX, not from OCR or layout guesses; maths comes with exact TeX in `alttext`; reading order is the source order.
- It has stable ids (`S4.T1`, `S3.p2`, `S3.E1`) that are mechanically checkable anchors. Use element id + char offset as the sidecar span.
- Trade-off: no page or bbox. If claims must cite a PDF page, also parse the PDF with Docling and align by text, or treat the HTML id as primary and the page as best-effort.
- Fall back to PDF when the page carries LaTeXML error markers (`ltx_ERROR` / conversion-error banners) [U: exact marker class not checked today], for versions without HTML, or when the citation must point at the version-of-record PDF.
- **LaTeX source** (`arxiv.org/src/<id>`, a tar.gz, confirmed) is the highest-fidelity input. Don't write your own converter: convert it with LaTeXML or latexml-oxide (public domain / CC0), or with Docling's LaTeX backend [U: quality not checked]. Pandoc is GPL-2.0; it is fine as an external binary but worth noting.
- For publisher papers, prefer JATS XML (e.g. PMC) via Docling's JATS backend when it is available, then the PDF.
- Use arXiv's bulk/S3 channels and respect the per-paper licences when caching full text.

## Sources

Releases and licences (GitHub API `/repos/<r>`, `/releases/latest`):
- https://github.com/docling-project/docling · https://github.com/docling-project/docling-mcp · https://github.com/docling-project/docling-core (provenance/table schema: `docling_core/types/doc/items/table/table_data.py`, `items/node.py`)
- https://github.com/docling-project/docling/blob/main/docling/datamodel/pipeline_options.py (OCR on, formula enrichment off by default)
- https://github.com/Unstructured-IO/unstructured (`unstructured/documents/elements.py`) · https://github.com/Unstructured-IO/unstructured-inference · https://github.com/Unstructured-IO/UNS-MCP
- https://github.com/microsoft/markitdown (incl. `packages/markitdown-mcp/README.md`, `_pdf_converter.py`)
- https://github.com/datalab-to/marker (README, MODEL_LICENSE) · https://github.com/datalab-to/surya
- https://github.com/opendatalab/MinerU (README, LICENSE.md) · https://opendatalab.github.io/MinerU/reference/output_files/
- https://github.com/grobidOrg/grobid (Readme.md) · https://github.com/kermitt2/pdfalto (GPL-2.0)
- https://github.com/facebookresearch/nougat
- https://github.com/pymupdf/pymupdf4llm · https://github.com/pymupdf/PyMuPDF/releases (2.1) · https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html
- https://github.com/allenai/olmocr
- https://github.com/brucemiller/LaTeXML (LICENSE: public domain) · https://github.com/dginev/latexml-oxide (CC0-1.0, "98%" claim)

PyPI (`https://pypi.org/pypi/<pkg>/json`): docling, docling-mcp, docling-serve, docling-ibm-models, unstructured, markitdown, markitdown-mcp, marker-pdf, surya-ocr, mineru, mineru-mcp, pymupdf, pymupdf4llm, pymupdf-layout, pymupdf4llm-mcp, nougat-ocr, olmocr.

Hugging Face model cards and API:
- https://huggingface.co/docling-project/docling-layout-heron · https://huggingface.co/docling-project/TableFormerV2 · https://huggingface.co/docling-project/docling-models · https://huggingface.co/docling-project/CodeFormulaV2 · https://huggingface.co/ibm-granite/granite-docling-258M
- https://huggingface.co/unstructuredio/yolo_x_layout (LICENSE.txt) · https://huggingface.co/microsoft/table-transformer-structure-recognition
- https://huggingface.co/datalab-to/indra-ocr · https://huggingface.co/datalab-to/surya-ocr-2.5
- https://huggingface.co/opendatalab/MinerU-4_models_torch · https://huggingface.co/opendatalab/MinerU2.5-Pro-2605-1.2B · https://huggingface.co/opendatalab/MinerU2.5-2509-1.2B
- https://huggingface.co/facebook/nougat-base · https://huggingface.co/allenai/olmOCR-2-7B-1025

Benchmarks:
- https://github.com/opendatalab/OmniDocBench (v1.6 leaderboard in README)
- https://github.com/allenai/olmocr (olmOCR-bench table in README)
- https://github.com/datalab-to/marker#benchmarks and https://huggingface.co/datasets/datalab-to/omni_parse_bench
- https://arxiv.org/html/2408.09869 (Docling Technical Report, Table 1)
- https://grobid.readthedocs.io/en/latest/benchmarks/Benchmarking/

arXiv source route:
- https://info.arxiv.org/about/accessible_HTML.html
- https://arxiv.org/html/1706.03762v7 and https://arxiv.org/html/2408.09869 (inspected: ids, MathML `alttext`, generator comment "LaTeXML oxide (version 0.7.6)")
- https://arxiv.org/src/2408.09869 (returns `arXiv-2408.09869v5.tar.gz`)
