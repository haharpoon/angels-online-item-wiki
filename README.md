# Angels Online item wiki

Searchable item list and paper doll, including update 26 fashion from `item9`.

Open `share/items/Angels Online Items.html` through a local web server, with this folder kept together. `icons` and `pd` have to sit next to the HTML. The same page is at `docs/items.html`.

Click a fashion, weapon, or mount row to put it on the dummy. Female-only clothes switch the dummy to female.

Rebuild the pages from `corpus/content.db`:

```
py -3 tools/build_item_wiki.py
py -3 tools/extract_local_pd.py
```

`extract_local_pd.py` reads an extracted client. Set `AO_EXTRACT` to that folder if it is not in the usual place.
