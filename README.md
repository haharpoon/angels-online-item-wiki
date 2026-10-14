# Angels Online item wiki

Searchable item list and paper doll, including update 26 fashion from `item9`.

GitHub's website will not run this page. The HTML is about 19 MB, so the file view says it can't show a file that big, and it would only show source anyway.

Download the whole repository (Code → Download ZIP) and unzip it. Open `docs/items.html`. Pictures are in `docs/icons` and the paper doll is in `docs/pd`, next to that file. `share/items/Angels Online Items.html` is the same page with its own `icons` and `pd` beside it, for handing the folder to someone. Keep whichever folder you open together.

Click a fashion, weapon, or mount row to put it on the dummy. Female-only clothes switch the dummy to female.

Rebuild the pages from `corpus/content.db`:

```
py -3 -m pip install -r requirements.txt
py -3 tools/build_item_wiki.py
py -3 tools/extract_local_pd.py
```

`extract_local_pd.py` reads `AO_EXTRACT` (see below). It is the paper-doll rebuild: doll rows for 紙娃娃 only, the ride path for mounts and mecha, and each normal clothes or weapon type's own component. It exits with an error if a catalog sprite has no PNG under `docs/pd/sprites`, or if an atlas is an 800×600 placeholder. Re-run that command after the client extract is in place so those sheets are decoded. `py -3 tools/extract_local_pd.py --repair` only retints and relinks ids already in the catalog; it does not read the client.

The build tools read client assets from the extracted client folder. `.env` provides the standard install-path default. To use a different extracted client folder on your machine, create `.env.local` in the project root with:

```dotenv
AO_EXTRACT="C:\path\to\your\extracted\client"
```

`.env.local` is ignored by Git, so machine-specific paths stay local. The process environment takes precedence over `.env.local`, which takes precedence over `.env`. When none provides `AO_EXTRACT`, the paper-doll extractor checks the usual Angels Online locations.

The item and paper-doll builds translate non-English names and descriptions locally with `dl-translate` and its M2M100 model. On first use, the model weights (about 1.9 GB) are downloaded and cached by Hugging Face; subsequent translations run locally, without sending item text to a translation service. Translations are also cached in `corpus/item_translations_en.json`, so later builds only translate new strings. The model and its Python dependencies require additional disk space and memory.
