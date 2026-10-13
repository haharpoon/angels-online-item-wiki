# Angels Online item wiki

Searchable item list and paper doll, including update 26 fashion from `item9`.

GitHub's website will not run this page. The HTML is about 19 MB, so the file view says it can't show a file that big, and it would only show source anyway.

Download the whole repository (Code → Download ZIP) and unzip it. Open `docs/items.html`. Pictures are in `docs/icons` and the paper doll is in `docs/pd`, next to that file. `share/items/Angels Online Items.html` is the same page with its own `icons` and `pd` beside it, for handing the folder to someone. Keep whichever folder you open together.

Click a fashion, weapon, or mount row to put it on the dummy. Female-only clothes switch the dummy to female.

Rebuild the pages from `corpus/content.db`:

```
py -3 tools/build_item_wiki.py
py -3 tools/extract_local_pd.py
```

`extract_local_pd.py` reads an extracted client. Set `AO_EXTRACT` to that folder if it is not in the usual place.
