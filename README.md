# Angels Online item wiki

Searchable item list and paper doll, including update 26 fashion from `item9`.

GitHub's website will not run this page. `items.html` is about 19 MB, so the file view says it can't show a file that big, and it would only show source anyway. Downloading that HTML file by itself also leaves out the pictures and the paper doll.

Download the whole repository (Code → Download ZIP) and unzip it. Then open `items.html` in that folder, or `docs/items.html`. Pictures are in `docs/icons`. The paper doll is in `docs/pd`. The root `items.html` uses `<base href="docs/">` so those folders resolve. `docs/items.html` and `share/items/Angels Online Items.html` expect `icons` and `pd` sitting next to the HTML. Keep the downloaded folder together.

Click a fashion, weapon, or mount row to put it on the dummy. Female-only clothes switch the dummy to female.

Rebuild the pages from `corpus/content.db`:

```
py -3 tools/build_item_wiki.py
py -3 tools/extract_local_pd.py
```

`extract_local_pd.py` reads an extracted client. Set `AO_EXTRACT` to that folder if it is not in the usual place.
