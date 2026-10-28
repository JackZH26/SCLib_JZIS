"""PNG provenance and fake-process attachment tests, not model vision evaluation."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json,struct,zlib
import pytest

from ingestion.materials_ner import page_images as images,providers
from ingestion.materials_ner.sources import Bundle,sha
from test_materials_ner_typed_inventory import inputs


def png(width=2,height=2,pixel=0):
    def chunk(kind,value):return struct.pack('>I',len(value))+kind+value+struct.pack('>I',zlib.crc32(kind+value)&0xffffffff)
    pixels=b''.join(b'\0'+bytes([pixel])*(width*3) for _ in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b'')


def fixture():
    original,*_=inputs();raw=original.model_dump();raw['documents'][0]['source_kind']='original_pdf';raw['blocks'][0]['locator']='pdf_page:1'
    original=Bundle.model_validate(raw)
    pages=[dict(pdf_sha256=original.documents[0].source_sha256,pdf_page=1,rendering={'producer':'authored-fixture'},raw=png())]
    return original,images.freeze(original,pages)


def test_pixel_capture_has_exact_source_page_identity_and_offline_bytes(tmp_path):
    b,c=fixture();assert images.verify(c,b,[b.blocks[0].id])==c
    inputs=images.materialize(c,b,tmp_path/'images with spaces');assert len(inputs)==1
    assert Path(inputs[0]['path']).read_bytes()==png()
    images.verify_receipt(images.receipt(inputs),c)
    Path(inputs[0]['path']).unlink()
    assert images.verify(c,b)==c  # Frozen replay uses captured bytes, not a mutable local file.


@pytest.mark.parametrize('variant',['wrong_page','wrong_pdf','wrong_pixel','wrong_dimension','bad_encoding','missing_image','duplicate_image','extra_trailing_bytes','crc'])
def test_source_and_binary_changes_are_rejected(variant):
    b,c=fixture()
    if variant=='wrong_page':c['pages'][0]['pdf_page']=2
    elif variant=='wrong_pdf':c['pages'][0]['pdf_sha256']='f'*64
    elif variant=='wrong_pixel':c['pages'][0]['sha256']='0'*64
    elif variant=='wrong_dimension':c['pages'][0]['width']+=1
    elif variant=='bad_encoding':c['pages'][0]['png_base64']='not base64'
    elif variant=='missing_image':c=images.freeze(b,[])
    elif variant=='duplicate_image':c['pages']*=2
    elif variant=='extra_trailing_bytes':
        with pytest.raises(ValueError):images.png_size(png()+b'x')
        return
    else:
        raw=bytearray(png());raw[-5]^=1
        with pytest.raises(ValueError):images.png_size(bytes(raw))
        return
    with pytest.raises(ValueError):images.verify(c,b,[b.blocks[0].id])


def fake_process(monkeypatch,mutate=None):
    commands=[]
    monkeypatch.setattr(providers.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout='authored-cli'))
    class Process:
        returncode=0
        def __init__(self,command,**kwargs):
            commands.append(command);self.command=command;self.events=kwargs['stdout']
        def communicate(self,**kwargs):
            output=Path(self.command[self.command.index('--output-last-message')+1]);output.write_text('{}')
            self.events.write((json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}})+'\n').encode());self.events.flush()
            if mutate:mutate()
    monkeypatch.setattr(providers.subprocess,'Popen',Process)
    return commands


def config():return dict(model='gpt-6-luna',reasoning='medium',timeout_seconds=1)


def test_codex_attaches_exact_files_and_keeps_worker_tools_disabled(monkeypatch,tmp_path):
    b,c=fixture();items=images.materialize(c,b,tmp_path/'attachments');commands=fake_process(monkeypatch)
    directory=tmp_path/'provider';directory.mkdir();settings=dict(config(),image_inputs=items)
    result=providers.CodexProvider(executable='/authored/codex').extract('authored prompt',{},settings,directory)
    argv=commands[0];assert argv[argv.index('--image')+1]==items[0]['path']
    assert '--enable' not in argv and argv[-1]=='-'
    assert all(argv[argv.index(feature)-1]=='--disable' for feature in ['shell_tool','multi_agent','image_generation','browser_use'])
    images.verify_receipt(json.loads((directory/'image-inputs.json').read_text()),c)
    assert result.text=='{}'


def test_changed_image_before_call_never_starts_a_provider(monkeypatch,tmp_path):
    b,c=fixture();items=images.materialize(c,b,tmp_path/'attachments');Path(items[0]['path']).write_bytes(png(pixel=1))
    commands=fake_process(monkeypatch)
    with pytest.raises(providers.ProviderFailure,match='provider_image_input_changed'):
        providers.CodexProvider(executable='/authored/codex').extract('test',{},dict(config(),image_inputs=items),tmp_path)
    assert commands==[]


def test_changed_image_during_call_rejects_the_result(monkeypatch,tmp_path):
    b,c=fixture();items=images.materialize(c,b,tmp_path/'attachments')
    fake_process(monkeypatch,lambda:Path(items[0]['path']).write_bytes(png(pixel=2)))
    with pytest.raises(providers.ProviderFailure,match='provider_image_input_changed'):
        providers.CodexProvider(executable='/authored/codex').extract('test',{},dict(config(),image_inputs=items),tmp_path)
    assert not (tmp_path/'image-inputs.json').exists()


def test_legacy_text_command_has_no_new_image_side_effects(monkeypatch,tmp_path):
    commands=fake_process(monkeypatch)
    providers.CodexProvider(executable='/authored/codex').extract('test',{},config(),tmp_path)
    assert '--image' not in commands[0] and not (tmp_path/'image-inputs.json').exists()


def test_other_provider_cannot_silently_drop_image_inputs(tmp_path):
    with pytest.raises(providers.ProviderFailure,match='responses_image_inputs_unsupported'):
        providers.ResponsesProvider().extract('test',{},dict(config(),image_inputs=[{'authored':True}]),tmp_path)
