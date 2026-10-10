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

The build tools read client assets from the extracted client folder. Set `AO_EXTRACT` in the project `.env` file to that folder, or set it in the process environment; the process environment takes precedence. When unset, the paper-doll extractor checks the usual Angels Online locations.

The item and paper-doll builds translate non-English names and descriptions locally with `dl-translate` and its M2M100 model. On first use, the model weights (about 1.9 GB) are downloaded and cached by Hugging Face; subsequent translations run locally, without sending item text to a translation service. Translations are also cached in `corpus/item_translations_en.json`, so later builds only translate new strings. The model and its Python dependencies require additional disk space and memory.
