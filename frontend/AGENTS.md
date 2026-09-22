# Default website language

- SCLib's default website UI is English throughout, including previews, field dictionaries, labels, buttons, placeholders, tooltips, validation errors, empty states and accessibility text.
- Keep scientific symbols and units unchanged. Preserve field identifiers, definitions, provenance and scoring semantics when changing copy.
- Keep `html lang="en"` and English metadata locales. Specify an English locale for displayed dates and numbers instead of inheriting the browser locale.
- Multilingual search queries, user-authored content and quoted research sources may retain their original language. Do not remove Chinese query recognition to enforce the UI default.
- Internal research plans and Markdown documents may remain Chinese. They are not website UI.
- Add English-default regression coverage when introducing new public UI copy.
