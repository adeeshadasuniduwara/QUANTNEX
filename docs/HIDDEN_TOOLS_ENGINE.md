# QUANTNEX Hidden Tools Engine — Web First

## Product behaviour

- The engine is not advertised in the QUANTNEX Web UI, navigation, dashboard, help, release notes or ordinary Telegram messages.
- It is discoverable only by the explicit Telegram command `/hidden_tools` after the user has connected their own Telegram bot and the local QUANTNEX worker is running.
- The command opens a paginated private capability catalogue. A user can invoke a tool by natural-language request or a named command; the dispatcher must only expose capabilities that are actually implemented and enabled.
- First delivery target is the local QUANTNEX Web/desktop installation. Android is a later port after the web implementation is stable.
- No tool is allowed to silently execute shell commands, arbitrary code, browser automation, financial transactions, broker orders, or destructive file operations. Such actions require separate explicit confirmation and policy gates.

## Runtime and privacy requirements

- Lazy-load each tool module only when invoked. Do not start a resident worker, preload ML models, or reserve large buffers while idle.
- Use bounded temporary files on the local device for supported file conversions. Delete temporary input/output files after delivery or a short cleanup TTL; do not add files to the QUANTNEX journal or persistent workspace unless the user explicitly asks.
- Enforce file size, page count, pixel count, archive expansion, execution-time and output-size limits before processing.
- Stream large inputs in chunks; avoid loading entire videos, PDFs or archives into RAM. Use OS temporary storage and bounded concurrency.
- Show a short progress response only when useful; do not publish the catalogue or internal tool activity in the Web UI or ordinary bot status messages.
- Telegram file uploads necessarily pass through Telegram's Bot API. After download, processing is local on the QUANTNEX host. Do not claim end-to-end local transfer.
- Do not send files to third-party AI/OCR services unless the user explicitly selects and approves that provider. Local-only tools must remain usable without cloud AI.
- Restrict commands to the connected chat ID; reject other chats. Do not expose bot tokens, file paths, internal errors or host details.
- Use per-user temporary workspaces and safe generated filenames. Never overwrite user files.
- Avoid idle RAM use: no polling loop or background model for this feature. Register the command in the existing Telegram worker and load tool code only on invocation.

## First useful tools to implement and test

1. Image/photo to PDF (multiple photos become one ordered PDF).
2. Extract embedded images from a PDF and return them individually, preferably as a ZIP for many images.
3. Inspect an image's visible contents and describe it. Local metadata/dimensions are deterministic; semantic vision requires an explicitly enabled vision provider and must be disclosed.
4. PDF metadata and page count.
5. Split PDF by page ranges.
6. Merge PDFs in the order explicitly supplied.
7. Compress PDF with quality controls.
8. Convert PDF pages to images.
9. Rotate PDF pages.
10. Extract text from text-based PDFs; OCR scanned PDFs only when a local OCR engine is installed and enabled.

## 100-tool capability catalogue

Catalogue entries are capability targets, not a claim that all 100 are implemented. A tool may be shown as available only after its implementation and tests are complete.

### Image tools (01–10)
01. Describe image contents (vision provider required for semantic description)
02. Convert one photo to PDF
03. Combine multiple photos into one PDF
04. Extract image metadata and dimensions
05. Resize image
06. Crop image
07. Rotate/flip image
08. Convert PNG/JPEG/WebP formats
09. Compress image
10. Create a contact sheet

### PDF tools (11–20)
11. Extract embedded images from PDF
12. Render PDF pages to PNG/JPEG
13. Extract selectable PDF text
14. Read PDF metadata and page count
15. Merge PDFs
16. Split PDF by page range
17. Rotate PDF pages
18. Compress/optimize PDF
19. Add page numbers
20. Create PDF from images

### Document tools (21–30)
21. DOCX to PDF
22. PDF to DOCX (text/layout limitations disclosed)
23. Extract DOCX text
24. Create DOCX from supplied text
25. Markdown to PDF
26. TXT to PDF
27. RTF to PDF
28. Extract tables from DOCX
29. Find and replace text in DOCX
30. Batch document conversion

### Spreadsheet tools (31–40)
31. Read XLSX sheet names
32. Preview spreadsheet rows
33. Export sheet to CSV
34. CSV to XLSX
35. Merge CSV files
36. Split CSV by row count
37. Remove duplicate rows
38. Filter rows by conditions
39. Summarize columns
40. Create a simple chart from spreadsheet data

### Archive and file tools (41–50)
41. ZIP files
42. Extract ZIP safely
43. List archive contents
44. Rename files in a batch
45. Organize files by extension
46. Find duplicate files by hash
47. Calculate file checksums
48. Inspect file metadata
49. Batch file conversion
50. Generate a file inventory report

### Text and writing tools (51–60)
51. Extract text from images (OCR engine required)
52. Detect text encoding
53. Convert text encoding
54. Clean whitespace and line endings
55. Find phrases in supplied documents
56. Compare two text files
57. Summarize supplied text (local or approved AI provider)
58. Translate supplied text (approved provider required)
59. Convert Markdown to HTML
60. Generate a plain-text report

### Audio tools (61–70)
61. Read audio metadata
62. Convert WAV/MP3/FLAC formats
63. Trim audio by time range
64. Normalize audio volume
65. Merge audio clips
66. Split audio by duration
67. Extract audio from video
68. Create waveform preview
69. Transcribe audio (local model/provider required)
70. Convert text to speech (local engine/provider required)

### Video tools (71–80)
71. Read video metadata
72. Extract video thumbnail
73. Extract frames at timestamps
74. Convert video formats
75. Compress video
76. Trim video by time range
77. Resize video
78. Merge video clips
79. Extract subtitles
80. Create a contact sheet from video frames

### Trading workspace utilities (81–90)
81. Calculate position size
82. Calculate pip/tick value from supplied contract specs
83. Calculate risk/reward
84. Calculate lot size from risk percentage and stop distance
85. Convert trading session time zones
86. Build a trade journal CSV export
87. Generate a local trade journal PDF report
88. Calculate drawdown statistics from supplied trade history
89. Validate a trading journal CSV
90. Create a paper-trade review checklist

### System and developer utilities (91–100)
91. Check QUANTNEX local service health
92. Show local app version
93. Inspect a log file with secrets redacted
94. Create a backup archive after confirmation
95. Verify a file checksum
96. Compare two JSON configuration files
97. Validate JSON syntax
98. Format JSON
99. Generate a diagnostic bundle with secrets excluded
100. Clean expired QUANTNEX temporary tool files

## Access and interaction

- `/hidden_tools` — show the catalogue, paginated.
- `/hidden_tools image`, `/hidden_tools pdf`, etc. — show one category.
- Natural-language requests are accepted only after the feature dispatcher can map them to an implemented tool with a safe, validated input schema.
- For example: send a photo with the caption `/photo_to_pdf` or select the image-to-PDF action; send a PDF with `/pdf_extract_images` to extract embedded images.
- Do not advertise unavailable entries as callable. Planned entries must be visibly marked as planned inside the private catalogue.

## Delivery phases

### H1 — secure hidden entry and file pipeline
- Add `/hidden_tools` without changing `/start`, the Web UI or normal menus.
- Add chat ownership checks, paginated catalogue and dispatcher.
- Add bounded Telegram file download, MIME/signature validation, safe temp workspace, cleanup and output delivery.
- Implement image-to-PDF and PDF image extraction with unit tests and real fixture files.

### H2 — document/PDF suite
- Add PDF metadata, text extraction, page rendering, split, merge, rotate and compression.
- Add DOCX/TXT/Markdown conversions where reliable libraries are available.

### H3 — office and archive tools
- Add spreadsheet and archive utilities with strict resource limits.

### H4 — media and trading utilities
- Add optional audio/video tools only when dependencies are installed; do not load them while idle.
- Add deterministic trading calculators and journal exports.

### H5 — hardening and Android port
- Security review, abuse/rate limits, file-size tests, cleanup tests, RAM profiling and user documentation.
- Port the same capability contracts to Android native storage APIs. Android does not run the Windows local worker and must not depend on a Windows-only path.

## Definition of done

The first release is done only when `/hidden_tools` works exclusively in the connected Telegram chat, the two first file workflows pass tests and real local-device checks, temp files are cleaned, the worker remains idle-light, and no hidden feature is exposed in the Web UI or ordinary bot menus. The full 100-item catalogue is a roadmap; entries must never be falsely presented as implemented.
