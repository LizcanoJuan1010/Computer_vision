
import os
import sys
import subprocess
import argparse
from pathlib import Path

def check_install(package):
    try:
        __import__(package)
        print(f"✓ {package} is installed")
        return True
    except ImportError:
        print(f"✗ {package} is NOT installed")
        return False

def convert_to_onnx(model_dir, output_dir, opset=11):
    print(f"\n[1/2] Converting to ONNX (Opset {opset})...")
    
    model_file = os.path.join(model_dir, "model.pdmodel")
    params_file = os.path.join(model_dir, "model.pdiparams")
    save_file = os.path.join(output_dir, "model.onnx")
    
    if not os.path.exists(model_file):
        print(f"Error: Model file not found: {model_file}")
        return False

    cmd = [
        "paddle2onnx",
        "--model_dir", model_dir,
        "--model_filename", "model.pdmodel",
        "--params_filename", "model.pdiparams",
        "--save_file", save_file,
        "--opset_version", str(opset),

        "--enable_onnx_checker", "True"
    ]
    
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"✓ ONNX conversion successful: {save_file}")
        return True
    else:
        print("✗ ONNX conversion failed!")
        print(result.stderr)
        return False

def print_trt_instructions(onnx_file):
    print(f"\n[2/2] TensorRT Conversion Instructions")
    print("-" * 50)
    print("To convert the generated ONNX to TensorRT, you need 'trtexec' (part of TensorRT SDK).")
    print("\nRun the following command:")
    print(f"\ntrtexec --onnx={onnx_file} --saveEngine=model.trt --fp16")
    print("-" * 50)

def main():
    parser = argparse.ArgumentParser(description="Convert Paddle Inference model to ONNX")
    parser.add_argument("--model_dir", default="inference_model/ppyoloe_person_finetune", help="Path to paddle inference model")
    parser.add_argument("--output_dir", default="onnx", help="Output directory")
    args = parser.parse_args()

    output_path = Path(args.output_dir)
    output_path.mkdir(exist_ok=True, parents=True)

    if not check_install("paddle2onnx"):
        print("\nPlease install paddle2onnx: pip install paddle2onnx")
        sys.exit(1)

    if convert_to_onnx(args.model_dir, args.output_dir):
        print_trt_instructions(output_path / "model.onnx")

if __name__ == "__main__":
    main()
