# Zotero metadata recognition beyond PDF/EPUB

## Bottom line

Zotero has two different mechanisms:

1. **Document recognition** is a private, format-specific orchestration path. For PDF, the desktop client locally extracts structured text/layout data, sends recognizer JSON plus the filename to Zotero's hosted recognizer, then resolves a returned arXiv ID, DOI, or ISBN through Zotero search translators; if no identifier resolves, it may create a basic item directly from server-returned title/authors/etc. For EPUB, recognition is mostly local: Zotero reads package RDF and scans the copyright page/first five sections for DOI/ISBN, resolves those through search translators, and falls back to embedded RDF. ([current Zotero source](https://github.com/zotero/zotero/blob/d54327a0459984e894599db2c783dfa88d4cd63e/chrome/content/zotero/xpcom/recognizeDocument.js#L338-L694))
2. **Add Item by Identifier** takes already-known ISBN/DOI/PMID/arXiv/ADS identifiers and runs search translators; it does not submit document text to the recognizer. ([official documentation](https://www.zotero.org/support/adding_items_to_zotero#add_item_by_identifier), [current lookup source](https://github.com/zotero/zotero/blob/d54327a0459984e894599db2c783dfa88d4cd63e/chrome/content/zotero/lookup.js#L39-L137))

There is **no supported/public API for submitting Markdown, plain text, or arbitrary extracted full text to Zotero's hosted recognizer**. Zotero's maintainer explicitly says PDF recognition is not publicly available, and the old recognizer-server was not intended for external consumption because it depends on internal server-side components. ([maintainer explanation](https://forums.zotero.org/discussion/80045/issues-with-pdf-metadata-retrieval-options), [follow-up on translation-server](https://groups.google.com/g/zotero-dev/c/9AmwvQqBCBY), [service discussion](https://forums.zotero.org/discussion/80101/zotero-service-for-metadata-extraction))

For this project, do not recreate that pipeline. Use native recognition while the original standalone PDF/EPUB still exists; import reviewed Markdown only after a parent item is known. If native recognition fails, extract a strong identifier from Markdown and run Zotero's identifier translator path. Title-based matching should remain an explicit, reviewed fallback.

## Native pipeline

### PDF

- `Zotero.PDFWorker.getRecognizerData()` reads the local PDF and produces recognizer data; recognition rejects PDFs with no text-bearing pages, so Zotero does not perform OCR here. ([client source](https://github.com/zotero/zotero/blob/d54327a0459984e894599db2c783dfa88d4cd63e/chrome/content/zotero/xpcom/recognizeDocument.js#L320-L389), [PDF worker manager](https://github.com/zotero/zotero/blob/d54327a0459984e894599db2c783dfa88d4cd63e/chrome/content/zotero/xpcom/pdfWorker/manager.js#L697-L730))
- Zotero posts the extracted recognizer JSON—not an ordinary translator search—to `${services.url}/recognizer/recognize`; the endpoint can be overridden only by internal preferences such as `recognize.url`. ([client source](https://github.com/zotero/zotero/blob/d54327a0459984e894599db2c783dfa88d4cd63e/chrome/content/zotero/xpcom/recognizeDocument.js#L346-L363), [endpoint construction](https://github.com/zotero/zotero/blob/d54327a0459984e894599db2c783dfa88d4cd63e/chrome/content/zotero/xpcom/recognizeDocument.js#L764-L786))
- Official documentation describes the payload as the **first few pages of text** and says the hosted service combines extraction algorithms, known Crossref metadata, and DOI/ISBN lookups; it does not require an account and Zotero says it does not log search content/results. ([official Retrieve PDF Metadata documentation](https://www.zotero.org/support/retrieve_pdf_metadata#how_it_works))
- Returned identifiers are tried in order: arXiv, DOI, then ISBN. arXiv/DOI use `Zotero.Translate.Search.setIdentifier()`; ISBN uses `setSearch({itemType: 'book', ISBN})`. If these fail but the service returned title/authors, Zotero creates a limited `journalArticle` or `bookSection` itself and labels the catalog `Zotero`. ([client source](https://github.com/zotero/zotero/blob/d54327a0459984e894599db2c783dfa88d4cd63e/chrome/content/zotero/xpcom/recognizeDocument.js#L391-L545))
- The process is inexact: only early pages are used, scanned/no-text PDFs need OCR first, and citations appearing early can cause rare false matches. Zotero recommends saving from an article/catalog landing page because web translators are usually faster and higher quality. ([official documentation](https://www.zotero.org/support/retrieve_pdf_metadata), [maintainer discussion of early-page false matches](https://forums.zotero.org/discussion/74713/pdf-metadata-retrieval-occasionally-incorrect))

### EPUB

EPUB does **not** use the hosted PDF recognizer. Zotero imports package RDF, extracts an ISBN from it when possible, scans the copyright page and up to five initial sections for DOI/ISBN, invokes search translation, verifies an ISBN result against the searched ISBN, then falls back to embedded RDF if lookup fails. ([current source](https://github.com/zotero/zotero/blob/d54327a0459984e894599db2c783dfa88d4cd63e/chrome/content/zotero/xpcom/recognizeDocument.js#L548-L694), [tests](https://github.com/zotero/zotero/blob/d54327a0459984e894599db2c783dfa88d4cd63e/test/tests/recognizeDocumentTest.js#L384-L659))

### Add Item by Identifier is separate

The identifier UI runs `Zotero.Utilities.extractIdentifiers()`, creates `Zotero.Translate.Search`, calls `setIdentifier()`, selects all matching search translators leniently, and saves their results. It supports ISBN, DOI, PMID, arXiv ID, and ADS Bibcode; provider choice is implemented by maintained search translators (for example Crossref/other DOI registries and library catalogs), not by document recognition. ([lookup source](https://github.com/zotero/zotero/blob/d54327a0459984e894599db2c783dfa88d4cd63e/chrome/content/zotero/lookup.js#L39-L137), [official provider summary](https://www.zotero.org/support/adding_items_to_zotero#add_item_by_identifier), [translator-type documentation](https://www.zotero.org/support/dev/translators#web_import_export_and_search))

## Markdown/API feasibility

### Direct reuse: no

Neither Zotero's documented Web API/Local API nor translation-server exposes the recognizer as an arbitrary-text endpoint. Translation-server's `/search` accepts a bibliographic identifier and `/web` accepts a webpage URL; its open PDF-recognition issue remains separate from normal translation. ([translation-server README](https://github.com/zotero/translation-server#endpoints), [PDF-recognition issue](https://github.com/zotero/translation-server/issues/38), [maintainer clarification](https://groups.google.com/g/zotero-dev/c/9AmwvQqBCBY))

Calling the recognizer URL discovered in client source with hand-built Markdown payloads would be relying on an undocumented private service and an undocumented PDF-layout schema. It is not a safe project dependency even though `recognize.url` exists for Zotero's own deployment/testing. ([client source](https://github.com/zotero/zotero/blob/d54327a0459984e894599db2c783dfa88d4cd63e/chrome/content/zotero/xpcom/recognizeDocument.js#L346-L363))

### Indirect reuse: identifiers first

A privileged Zotero extension can safely follow the same **translator machinery** used by Add Item by Identifier:

```js
const ids = Zotero.Utilities.extractIdentifiers(markdown);
const translate = new Zotero.Translate.Search();
translate.setIdentifier(ids[0]);
translate.setTranslator(await translate.getTranslators());
const items = await translate.translate({ libraryID, saveAttachments: false });
```

The stable source entry points are `Zotero.Utilities.extractIdentifiers()` and `Zotero.Translate.Search` with `setIdentifier()`, as exercised by Zotero's own lookup UI. They are privileged desktop-JavaScript APIs, however, not a versioned remote/public API; keep them behind this project's narrow extension bridge and test against supported Zotero versions. ([lookup source](https://github.com/zotero/zotero/blob/d54327a0459984e894599db2c783dfa88d4cd63e/chrome/content/zotero/lookup.js#L39-L137), [Zotero plugin-development guidance](https://www.zotero.org/support/dev/zotero_7_for_developers))

Practical order:

1. Extract and normalize DOI, ISBN, PMID, arXiv ID, or ADS Bibcode from Markdown/plain text; use Zotero's identifier extraction rather than new regexes where possible. ([lookup source](https://github.com/zotero/zotero/blob/d54327a0459984e894599db2c783dfa88d4cd63e/chrome/content/zotero/lookup.js#L51-L53))
2. Resolve through `Translate.Search`; this reuses Zotero's maintained search translators and their fallback ordering. ([translator priority documentation](https://www.zotero.org/support/dev/translators/priority#search_translators))
3. Only if there is no identifier, consider a structured `setSearch()` query containing title plus author/year. Search translators can accept search objects, but title-only behavior is translator-dependent and is not the Add Item by Identifier contract; require review before creating/merging an item. ([search-translator documentation](https://www.zotero.org/support/dev/translators), [EPUB's structured-search example](https://github.com/zotero/zotero/blob/d54327a0459984e894599db2c783dfa88d4cd63e/chrome/content/zotero/xpcom/recognizeDocument.js#L581-L617))

## Relevant plugins

No maintained Zotero 7/8/9 plugin found in the primary-source search directly treats a Markdown attachment as if it were a PDF and feeds it into Zotero's native recognizer. The credible current tools instead parse pasted text themselves or recover already-embedded bibliographic data.

| Project | What source verifies | Relevance | Status |
|---|---|---|---|
| [Zotero Add Items from Text](https://github.com/jmiba/Zotero-add-items-from-text) | Accepts pasted unstructured references, asks Gemini/OpenAI-compatible/Ollama to produce structured records, optionally validates/enriches against Crossref, OpenAlex, library catalogs, and Wikidata, previews, then creates Zotero items. The implementation is visible in [`src/llm`](https://github.com/jmiba/Zotero-add-items-from-text/tree/main/src/llm), [`src/indices.ts`](https://github.com/jmiba/Zotero-add-items-from-text/blob/main/src/indices.ts), and [`src/import.ts`](https://github.com/jmiba/Zotero-add-items-from-text/blob/main/src/import.ts). | **Direct match for arbitrary plain/Markdown text**, but it is a separate AI/index pipeline, not Zotero recognition. Network/privacy/model-quality and false-match review apply. | Active, source available; latest release `v1.0.12` explicitly adds Zotero 9 compatibility, after Zotero 7/8 releases. ([releases](https://github.com/jmiba/Zotero-add-items-from-text/releases)) |
| [Zotero Smart Clipboard Import](https://github.com/rikochyou/zotero-smart-clipboard-import) | Detects DOI, URL, BibTeX, and plain-text citations from clipboard; resolves with doi.org/Crossref/Semantic Scholar/OpenAlex, optionally uses an OpenAI-compatible LLM, previews, and creates items. Source separates [`contentDetector`](https://github.com/rikochyou/zotero-smart-clipboard-import/blob/main/src/modules/contentDetector.ts), [`metadataResolver`](https://github.com/rikochyou/zotero-smart-clipboard-import/blob/main/src/modules/metadataResolver.ts), and [`itemCreator`](https://github.com/rikochyou/zotero-smart-clipboard-import/blob/main/src/modules/itemCreator.ts). | **Direct match for clipboard/plain text**; a Markdown document can be copied into it, but there is no Markdown-file attachment recognition and no native recognizer reuse. | Active but very new/low-adoption (`v0.1.38`); README/manifest target Zotero 7, so Zotero 8/9 should be treated as unverified until tested. ([releases](https://github.com/rikochyou/zotero-smart-clipboard-import/releases), [manifest](https://github.com/rikochyou/zotero-smart-clipboard-import/blob/main/addon/manifest.json)) |
| [Reference Extractor](https://github.com/rmzelle/ref-extractor) | Locally extracts CSL JSON/BibTeX/RIS from Zotero/Mendeley field codes already embedded in DOCX/ODT, which Zotero can then import. ([source/README](https://github.com/rmzelle/ref-extractor)) | Relevant **DOCX recovery**, but not a Zotero plugin and not recognition of arbitrary document prose; it works only when citation metadata is already embedded. | Source available and established; last repository update shown in 2024. Format-based, so not tied to Zotero 7/8/9 runtime APIs. |
| [ODF/DOCX Scan for Zotero](https://github.com/Juris-M/zotero-odf-scan-plugin) | Converts known Scannable Cite or Pandoc citation-key markers in ODT/DOCX into active Zotero citations. | Maintained, but **not metadata recognition/creation**: referenced items must already exist in Zotero. Included to prevent mistaking DOCX support for recognition. | Active Zotero add-on with current releases. ([README](https://github.com/Juris-M/zotero-odf-scan-plugin), [releases](https://github.com/Juris-M/zotero-odf-scan-plugin/releases)) |

Excluded as irrelevant: Markdown note/export/link plugins such as Mdnotes, Better Notes, and MarkDB-Connect do not derive new bibliographic records from Markdown; Mdnotes also explicitly says it is incompatible with Zotero 7. ([Mdnotes status](https://github.com/argenos/zotero-mdnotes), [MarkDB-Connect scope](https://github.com/daeh/zotero-markdb-connect))

## Smallest project design

1. **Keep the original PDF/EPUB standalone long enough for Zotero to recognize it natively.** Invoke `Zotero.RecognizeDocument.recognizeItems([attachment])` only for inputs that pass `canRecognize()`, then use the resulting parent item. This preserves Zotero's own identifiers, translators, collection handling, attachment parenting, and rename behavior. ([recognition orchestration](https://github.com/zotero/zotero/blob/d54327a0459984e894599db2c783dfa88d4cd63e/chrome/content/zotero/xpcom/recognizeDocument.js#L92-L318))
2. **After parent creation, use the existing reviewed Markdown Full Text import unchanged.** This matches the repository's current separation: PDF/EPUB establishes bibliographic identity; Markdown is a child representation, not an identity source. ([project ingest design](../ingest.md))
3. **Fallback only after native recognition returns no match.** Read the Markdown locally, call Zotero's existing `extractIdentifiers()`, and resolve exactly one strong identifier through `Translate.Search`; attach/import Markdown only after duplicate checks and explicit confirmation.
4. **Do not build title/author fuzzy matching yet.** If identifiers are absent, leave the attachment unresolved or offer manual entry. Add a reviewed title+author+year search only after real failed-ingest examples justify it. This avoids duplicating Zotero's private recognizer and avoids silent wrong-parent creation.
5. **Do not add a plugin dependency.** The two text-import plugins demonstrate viable fallback approaches but add AI providers, multiple metadata APIs, preview UI, and separate matching policy. None is needed for the narrow PDF/EPUB-first flow.

## Open decision

Decide one policy point before implementation: when native PDF/EPUB recognition fails but Markdown contains **exactly one normalized strong identifier**, may the extension create the parent automatically through `Translate.Search`, or must it return a dry-run candidate for explicit confirmation? The safer default for zotero-agentibility is **dry-run/confirm**, because identifier extraction can find citations to other works and native recognition itself is designed to use more context than a regex hit.
