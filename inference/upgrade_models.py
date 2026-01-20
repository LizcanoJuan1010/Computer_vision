import os
import urllib.request
import tarfile
import subprocess
import shutil
import sys

# URLs (List for fallback)
URLS = {
    "cls": ["https://paddleocr.bj.bcebos.com/dygraph_v2.0/ch/ch_ppocr_mobile_v2.0_cls_infer.tar"],
    "stgcn": [
        "https://bj.bcebos.com/v1/paddledet/models/pipeline/STGCN.tar",
        "https://paddledet.bj.bcebos.com/models/pipeline/STGCN.tar",
        "https://videotag.bj.bcebos.com/PaddleVideo/Release/2.2/PPHuman/STGCN.tar"
    ]
}

# Destinations
DEST_DIRS = {
    "cls": "/app/weights/ocr/cls",
    "stgcn": "/app/weights/action"
}

# New Filenames
FILENAMES = {
    "cls": "cls_reexport.onnx",
    "stgcn": "stgcn_reexport.onnx"
}

def install_deps():
    print("📦 Installing paddle2onnx...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paddle2onnx", "paddlepaddle-gpu"]) # Ensure paddle avail

def download_and_extract(url_list, name):
    filename = f"{name}.tar"
    
    success = False
    for url in url_list:
        try:
            print(f"⬇️ Downloading {name} from {url}...")
            urllib.request.urlretrieve(url, filename)
            success = True
            break
        except Exception as e:
            print(f"   ⚠️ Fail: {e}")
            
    if not success:
        raise Exception(f"All URLs failed for {name}")
    
    print(f"📦 Extracting {name}...")
    with tarfile.open(filename) as tar:
        tar.extractall()
        # Returns the directory name usually
        return tar.getnames()[0].split('/')[0]

def convert(model_dir, output_path):
    print(f"🔄 Converting {model_dir} to {output_path}...")
    # Find .pdmodel and .pdiparams
    files = os.listdir(model_dir)
    pdmodel = next((f for f in files if f.endswith(".pdmodel") or f == "inference.pdmodel"), None)
    pdiparams = next((f for f in files if f.endswith(".pdiparams") or f == "inference.pdiparams"), None)

    if not pdmodel or not pdiparams:
        print(f"❌ Could not find pdmodel/pdiparams in {model_dir}")
        return False
    
    pdmodel_path = os.path.join(model_dir, pdmodel)
    pdiparams_path = os.path.join(model_dir, pdiparams)
    
    cmd = [
        "paddle2onnx",
        "--model_dir", model_dir,
        "--model_filename", pdmodel,
        "--params_filename", pdiparams,
        "--save_file", output_path,
        "--opset_version", "16", # Use a high opset (16 or 17) for best support
        "--enable_onnx_checker", "True"
    ]
    
    print(f"   Executing: {' '.join(cmd)}")
    subprocess.check_call(cmd)
    return True

def main():
    install_deps()
    
    for key, url in URLS.items():
        try:
            # 1. Download
            extract_dir = download_and_extract(url, key)
            
            # 2. Convert
            output_onnx = FILENAMES[key]
            if convert(extract_dir, output_onnx):
                # 3. Move to Dest
                dest_dir = DEST_DIRS[key]
                dest_path = os.path.join(dest_dir, output_onnx)
                
                # Verify dir exists
                if not os.path.exists(dest_dir):
                    os.makedirs(dest_dir)

                print(f"🚚 Moving {output_onnx} to {dest_path}")
                shutil.move(output_onnx, dest_path)
                print(f"✅ Success for {key}!")
            else:
                print(f"❌ Conversion failed for {key}")
                
        except Exception as e:
            print(f"❌ Error processing {key}: {e}")

if __name__ == "__main__":
    main()
