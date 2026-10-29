import sys, os, tempfile, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools_security.validate_path import register_basepath
register_basepath("/tmp")

os.environ["LAMA_OLE_DOCSEARCH_BACKEND"] = "echo"
os.environ["LAMA_OLE_DOCSEARCH_MODEL"] = "echo-mock"

from tools.doc_search_tools import doc_index, doc_search, doc_index_status, doc_get_chunk

d = tempfile.mkdtemp()
docs = os.path.join(d, "docs")
os.makedirs(docs)
with open(os.path.join(docs, "readme.md"), "w") as f:
    f.write("# Hello\nThis is a test document about LSP tools.\nAnother line here.\n")
with open(os.path.join(docs, "guide.txt"), "w") as f:
    f.write("Guide to configuration.\nSet keep_alive to 5m.\n")

db = os.path.join(d, "db")
os.environ["LAMA_OLE_DOCSEARCH_DB"] = db

res = doc_index(docs)
print("INDEX:", json.dumps(res, indent=2))

res = doc_index_status()
print("STATUS:", json.dumps(res, indent=2))

res = doc_search("keep_alive")
print("SEARCH:", json.dumps(res, indent=2)[:500])

res = doc_search('(r "keep_alive")')
print("REGEX SEARCH:", json.dumps(res, indent=2)[:300])