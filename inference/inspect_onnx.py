import onnx
import sys

MODELS = [
    "/app/weights/action/stgcn.onnx",
    "/app/weights/ocr/cls/cls.onnx"
]

def inspect():
    for path in MODELS:
        print(f"📦 Inspecting {path}...")
        try:
            model = onnx.load(path)
            print(f"  ✅ Loaded. Opset: {model.opset_import[0].version}")
            
            # Find Concat nodes
            for node in model.graph.node:
                if node.op_type == "Concat":
                    print(f"  🔍 Found Concat Node: {node.name}")
                    for attr in node.attribute:
                        if attr.name == "axis":
                            print(f"     Axis: {attr.i}")
        except Exception as e:
            print(f"  ❌ Failed to load/inspect: {e}")

if __name__ == "__main__":
    inspect()
