# Zotero-Agentibility

A literature library that lets people and agents work from the same Zotero-managed records and synchronized full text.

## Project principle

**Human intent, Zotero ownership**:
The human researcher directs goals and policy; Zotero is the sole system of record and owner of library data, attachment storage, synchronization state, and transactions. Zotero-Agentibility may expose broad, fine-grained Agent control—including discovery assistance, adding documents, metadata resolution, organization, and duplicate handling—but every mutation remains visible, policy-controlled, and executed through a fixed validated Zotero-native operation. Read-only catalog access may accelerate retrieval but never becomes a write path.
_Avoid_: direct SQLite or storage writes, arbitrary JavaScript execution, hidden mutations, an independent literature database, treating an Agent's working files as a second source of truth

## Language

**Literature Item**:
A bibliographic record that may belong to multiple **Collections** and have one or more attached representations. It is addressed by its stable **Item Key**, not by its mutable title.
_Avoid_: File, folder

**Item Key**:
The stable Zotero identifier of one **Literature Item**, used to distinguish items whose titles may change or collide.
_Avoid_: Title, filename, citation key

**Unrecognized Document**:
A top-level PDF or EPUB attachment that has not yet been resolved to a **Literature Item**. It may belong to Collections, but it is not a **Source Document** until metadata resolution creates or reuses a parent Literature Item.
_Avoid_: Literature Item, Source Document, orphan PDF

**Strong Identifier**:
A normalized DOI, ISBN, arXiv ID, PMID, or ADS Bibcode that can identify a bibliographic work through Zotero's search translators. Automatic metadata resolution requires an exact, unambiguous Strong Identifier; title similarity alone is not sufficient.
_Avoid_: Title match, filename, fuzzy match

**Metadata Resolution**:
The accuracy-first process that turns an **Unrecognized Document** into a **Literature Item** by using Zotero's native document recognizer first and an exact, unambiguous **Strong Identifier** lookup second. If neither result can be verified, the document remains unresolved rather than receiving guessed metadata.
_Avoid_: Manual parent creation, title-only matching, best-effort guessing

**Source Document**:
The selected original full-text representation attached to a **Literature Item**, normally a PDF and sometimes a sole EPUB. `za-cli:pdf` disambiguates only PDFs; a sole EPUB is an unmarked fallback. Adding another document attachment does not replace the Source Document.
_Avoid_: Markdown, note, any document attachment

**Markdown Full Text**:
A text-first representation stored as a Zotero-owned child attachment of the same **Literature Item**. It is never a Zotero Note, even when a Note contains Markdown syntax. A Literature Item has exactly one designated Markdown Full Text once converted; it is preserved exactly as produced, including image references whose target files are not retained.
_Avoid_: Note, annotation, summary, cleaned Markdown

**Passage**:
A line-addressable portion of a **Markdown Full Text** or fallback PDF **Source Document** used for retrieval and exact verification. EPUB can establish identity and be reported as a source, but it requires reviewed Markdown before Passage reading or indexing. A Passage retains its source and location and is not a summary.
_Avoid_: Summary, unsupported answer

**Collection**:
A named grouping of **Literature Items**. A Literature Item may belong to multiple Collections; removing it from one Collection removes only that membership, not the Literature Item from the library.
_Avoid_: Folder, directory

**Collection Key**:
The stable Zotero identifier used to disambiguate Collections with the same path name. Paths remain the normal navigation interface.
_Avoid_: Item Key, Collection name

**Collection Membership**:
The relationship that makes one **Literature Item** appear in a **Collection**. Multiple memberships reference the same Literature Item rather than creating copies.
_Avoid_: Copy, duplicate, virtual file

**Unfiled Item**:
A **Literature Item** with no Collection Membership. It appears directly under the active library during navigation; items already filed in Collections are found there or through library-wide search.
_Avoid_: Deleted item, all-library listing

**Duplicate Item**:
A second **Literature Item** with the same stable scholarly identifier or identical **Source Document** as an existing item. Similar titles, authors, or years identify only a possible duplicate and are not sufficient for automatic reuse or merging.
_Avoid_: Another Collection Membership, similar paper

**Trash**:
Zotero's recoverable destination for items, attachments, or Collections removed through the CLI. The CLI never permanently purges Trash.
_Avoid_: Permanent deletion, removal from a Collection

## Example dialogue

> **Researcher:** Which paper does this title path refer to?
>
> **Agent:** Literature Items are addressed by Item Key rather than title paths, so the reference is unambiguous.
>
> **Researcher:** Delete the duplicate permanently.
>
> **Agent:** I can merge it and move the Duplicate Item to Trash, but permanent purging remains a Zotero UI operation.
>
> **Researcher:** This new paper has the same DOI as an existing Literature Item. Should we add another one?
>
> **Agent:** No. I will reuse the existing Literature Item and add the requested Collection Membership. A merely similar title would require review instead.
>
> **Researcher:** What does listing My Library show?
>
> **Agent:** Its top-level Collections and Unfiled Items. I use library-wide search rather than listing every Literature Item.
>
> **Researcher:** If I remove this Literature Item from one Collection, is it deleted from the library?
>
> **Agent:** No. Only that Collection Membership is removed; the same Literature Item and its other memberships remain.
>
> **Researcher:** Can two agents inspect different Collections at the same time?
>
> **Agent:** Yes. Each command names its Collection path or Collection Key, so concurrent work has no shared navigation state.
>
> **Researcher:** The semantic result mentions a stability proof. Can you verify it?
>
> **Agent:** I will read the matched Passage by its source lines before making the claim; I do not need to load the entire paper.
>
> **Researcher:** Does this Literature Item have Markdown Full Text?
>
> **Agent:** Yes. It has exactly one designated Markdown Full Text, so I will read and search that instead of extracting the Source Document. The item also belongs to two Collections.
>
> **Researcher:** Will its converted figures be synchronized?
>
> **Agent:** No. Markdown Full Text is synchronized unchanged, including its original image references, but the extracted image files are not retained.
