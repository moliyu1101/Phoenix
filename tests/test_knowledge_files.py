import json
import os

import httpx
import pytest

from phoenix.filesystem import SecureFiles, relative_parts
from phoenix.knowledge import Knowledge, chunk_text, cosine, terms


def test_fts_retrieval_and_category(components):
    did=components.knowledge.ingest('Special polynomial clue','bivariate polynomial lattice parameters','crypto',trusted=True)
    assert components.knowledge.search('bivariate polynomial','crypto')[0]['doc_id']==did
    assert not any(x['doc_id']==did for x in components.knowledge.search('bivariate polynomial','web'))


def test_draft_is_excluded(components):
    did=components.knowledge.ingest('Unreviewed','uniqueunreviewedconcept',trusted=False)
    assert components.knowledge.search('uniqueunreviewedconcept')==[]
    components.knowledge.trust(did,True)
    assert components.knowledge.search('uniqueunreviewedconcept')[0]['doc_id']==did


def test_cjk_bigram_retrieval(components):
    did=components.knowledge.ingest('Chinese note','\u8bc1\u636e\u9a71\u52a8\u7684\u77e5\u8bc6\u84b8\u998f',trusted=True)
    assert components.knowledge.search('\u77e5\u8bc6\u84b8\u998f')[0]['doc_id']==did


def test_query_syntax_not_executable(components):
    assert isinstance(components.knowledge.search('" OR * NOT ( ; DROP TABLE documents; --'),list)
    assert components.store.one('SELECT COUNT(*) AS n FROM documents')['n']==12


def test_snapshot_freezes_visible_docs(components):
    a=components.knowledge.ingest('a','frozenquery alpha',trusted=True)
    b=components.knowledge.ingest('b','frozenquery beta',trusted=True)
    assert all(x['doc_id']==a for x in components.knowledge.search('frozenquery',snapshot=[a]))
    assert components.knowledge.search('frozenquery',snapshot=[])==[]


def test_dense_hybrid_and_space_isolation(components):
    a=components.knowledge.ingest('vector a','semantic-topic-one',trusted=True)
    b=components.knowledge.ingest('vector b','different-topic-two',trusted=True)
    components.store.execute('UPDATE chunks SET embedding=?,embedding_space=? WHERE doc_id=?',('[1,0]','space-a',a))
    components.store.execute('UPDATE chunks SET embedding=?,embedding_space=? WHERE doc_id=?',('[0,1]','space-b',b))
    result=components.knowledge.search('no_keyword_match',vector=[1,0],space='space-a')
    assert result[0]['doc_id']==a
    assert all(x['doc_id']!=b for x in result)


def test_chunk_bounds_and_overlap():
    chunks=chunk_text('a'*10000,1000,100)
    assert len(chunks)>10 and all(len(x)<=1000 for x in chunks)
    assert cosine([1,0],[1,0])==1
    assert cosine([1],[1,2])==-1


@pytest.mark.parametrize('path',['../x','/etc/passwd','a/../../x','C:\\secret','a\\b','x\x00y','a:b'])
def test_path_rejected(path,tmp_path):
    with pytest.raises(ValueError):SecureFiles(tmp_path).write(path,b'x')


def test_symlink_escape_read_write(tmp_path):
    outside=tmp_path.parent/'outside-file';outside.write_text('secret')
    fs=SecureFiles(tmp_path)
    (tmp_path/'link').symlink_to(outside)
    with pytest.raises(OSError):fs.read('link')
    with pytest.raises(OSError):fs.write('link',b'bad',overwrite=True)
    assert outside.read_text()=='secret'


def test_parent_symlink_escape(tmp_path):
    outside=tmp_path.parent/'outside-dir';outside.mkdir(exist_ok=True)
    fs=SecureFiles(tmp_path);(tmp_path/'dir').symlink_to(outside,target_is_directory=True)
    with pytest.raises(OSError):fs.write('dir/evil',b'x')
    assert not (outside/'evil').exists()


def test_file_read_write_pages(tmp_path):
    fs=SecureFiles(tmp_path);fs.write('dir/test',b'abcdefgh')
    assert fs.read('dir/test',2,3)==b'cde'
    with pytest.raises(FileExistsError):fs.write('dir/test',b'x')
    fs.write('dir/test',b'x',overwrite=True)
    assert fs.list()==[{'path':'dir/test','size':1}]


async def test_embedding_requires_paid_ack_and_indexes(components):
    components.settings.embedding_base_url='https://embeddings.invalid/v1'
    components.settings.embedding_model='test-embedding'
    def handler(request):
        data=json.loads(request.content)
        return httpx.Response(200,json={'data':[{'index':i,'embedding':[1.0,0.0]} for i in range(len(data['input']))],
                                        'usage':{'prompt_tokens':12}})
    k=Knowledge(components.store,components.settings,httpx.MockTransport(handler))
    did=k.ingest('Vector test','index this sample',trusted=True)
    with pytest.raises(ValueError):await k.index(did)
    assert await k.index(did,True)==1
    assert components.store.one('SELECT embedding FROM chunks WHERE doc_id=?',(did,))['embedding']


async def test_embedding_invalid_dimensions(components):
    components.settings.embedding_base_url='https://embeddings.invalid/v1';components.settings.embedding_model='test'
    def handler(request):return httpx.Response(200,json={'data':[{'index':0,'embedding':[]}], 'usage':{}})
    k=Knowledge(components.store,components.settings,httpx.MockTransport(handler))
    with pytest.raises(ValueError):await k.embed(['test'])
