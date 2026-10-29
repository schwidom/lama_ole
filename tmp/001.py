import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from doc_search.lisp import parse, validate
print("parse bare:", parse("hello world"))
print("parse lisp:", parse('(and (q "lsp") (r ".*\\.md"))'))
validate(parse('(and (q "lsp") (r ".*\\.md"))'))
print("lisp OK")

from doc_search.chunker import chunk_text
chunks = chunk_text("line1\nline2\nline3", chunk_lines=2, overlap=0)
print("chunks:", chunks)
print("chunker OK")

from doc_search.store import connect, db_path_for
import tempfile
d = tempfile.mkdtemp()
dbp = db_path_for(d, "test-model")
conn = connect(dbp)
print("db connected, schema OK")
conn.close()

from backends.factory import create_backend
b = create_backend("echo")
print("embed:", b.embed(["hello", "world"], "m")[:1])
print("backend OK")

from tools.doc_search_tools import doc_index, doc_search
print("tools imported OK")
