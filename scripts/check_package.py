"""Verify the delivered archive, source parity and absence of runtime dependencies."""
import hashlib
import json
import re
import zipfile
from build import ROOT, ARCHIVE_PATH, NAME, setting

source=ROOT/"src"/f"{NAME}.setting"
archive=ROOT/"dist/FrameEcho.drfx"
raw=source.read_bytes()
assert raw==setting().encode("utf-8"),"Generated source is stale"
with zipfile.ZipFile(archive) as z:
    assert z.namelist()==[ARCHIVE_PATH],z.namelist()
    assert z.read(ARCHIVE_PATH)==raw
    assert z.testzip() is None
text=raw.decode("utf-8")
allowed={"GroupOperator","PipeRouter","Transform","TimeStretcher","Dissolve","Dimension.OpticalFlow","VectorMotionBlur","DirectionalBlur","EllipseMask","PolylineMask","BezierSpline","RectangleMask"}
node_types=re.findall(r"(?:FrameEcho|FE_\w+)\s*=\s*([\w.]+)\s*\{",text)
assert set(node_types)==allowed,set(node_types)
assert text.count("MainInput1 = InstanceInput")==1
assert text.count("MainOutput1 = InstanceOutput")==1
assert len(re.findall(r"\bInput\d+ = InstanceInput",text))==1
assert len(re.findall(r"\bInput\d+ = Input \{",text))==25
assert 'Input22 = Input { Value = 0, }' in text
assert 'INPID_InputControl = "LabelControl", LBLC_NumInputs = 5' in text
nest=text.index('Input22 = { INP_External = false')
assert nest < text.index('Input21 = { LINKID_DataType = "Number"', nest) < text.index('Input23 = { LINKID_DataType = "Point"', nest)
assert 'SourceOp = "FE_Pen", Source = "Polyline"' in text
for forbidden in ["Loader {",".fuse",".ofx","require(","dofile(","loadfile(","io.","os.","Setting:","/Users/","C:\\\\","GlobalStart","GlobalEnd"]:
    assert forbidden not in text,forbidden
digest=hashlib.sha256(archive.read_bytes()).hexdigest()
assert (ROOT/"dist/SHA256SUMS.txt").read_text().split()[0]==digest
report={"pass":True,"sha256":digest,"archive_entries":[ARCHIVE_PATH],"native_node_types":sorted(allowed),"native_node_count":len(node_types),"image_inputs":1,"image_outputs":1,"published_controls":26,"external_runtime_dependencies":[]}
(ROOT/"validation/package-results.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
print(json.dumps(report,ensure_ascii=False,indent=2))
