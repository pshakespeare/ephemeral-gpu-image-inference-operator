"""Run image inference on GPU."""

import argparse
import json
import time
from pathlib import Path

import torch
import torchvision
from torchvision import transforms
from PIL import Image


def load_model(model_name):
    """Load pretrained model."""
    if model_name == "resnet50":
        model = torchvision.models.resnet50(weights="ResNet50_Weights.DEFAULT")
    elif model_name == "mobilenet_v3_small":
        model = torchvision.models.mobilenet_v3_small(
            weights="MobileNet_V3_Small_Weights.DEFAULT"
        )
    else:
        raise ValueError(f"Unknown model: {model_name}")
    
    model.eval()
    return model


def preprocess_image(image_path):
    """Preprocess image for inference."""
    transform = transforms.Compose(
        [
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
            ),
        ]
    )
    
    image = Image.open(image_path).convert("RGB")
    image_tensor = transform(image).unsqueeze(0)
    return image_tensor


def get_imagenet_labels():
    """Get ImageNet class labels."""
    # For demo, return simplified labels
    # In production, load from imagenet_classes.txt or use torchvision.datasets
    labels = []
    # Common ImageNet classes (first 20 as example)
    common_classes = [
        "tench", "goldfish", "great white shark", "tiger shark", "hammerhead",
        "electric ray", "stingray", "cock", "hen", "ostrich",
        "brambling", "goldfinch", "house finch", "junco", "indigo bunting",
        "robin", "bulbul", "jay", "magpie", "chickadee"
    ]
    # Fill with common classes, then generic class names
    for i in range(1000):
        if i < len(common_classes):
            labels.append(common_classes[i])
        else:
            labels.append(f"class_{i}")
    return labels


def run_inference(model, image_tensor, device):
    """Run inference on image."""
    model = model.to(device)
    image_tensor = image_tensor.to(device)
    
    start_time = time.time()
    with torch.no_grad():
        outputs = model(image_tensor)
        probabilities = torch.nn.functional.softmax(outputs[0], dim=0)
    
    elapsed_ms = (time.time() - start_time) * 1000
    
    # Get top 5 predictions
    top5_prob, top5_indices = torch.topk(probabilities, 5)
    
    labels = get_imagenet_labels()
    top5 = [
        {
            "label": labels[idx.item()],
            "probability": prob.item(),
        }
        for prob, idx in zip(top5_prob, top5_indices)
    ]
    
    return top5, elapsed_ms


def main():
    """Main inference function."""
    parser = argparse.ArgumentParser(description="Run GPU image inference")
    parser.add_argument("--model", required=True, choices=["resnet50", "mobilenet_v3_small"])
    parser.add_argument("--input", required=True, help="Input image path")
    parser.add_argument("--output", required=True, help="Output JSON path")
    
    args = parser.parse_args()
    
    # Check for GPU
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        raise RuntimeError("CUDA not available! GPU is required for this job.")
    
    print(f"Using device: {device}")
    print(f"CUDA device: {torch.cuda.get_device_name(0)}")
    
    # Load model
    print(f"Loading model: {args.model}")
    model = load_model(args.model)
    
    # Load and preprocess image
    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input image not found: {args.input}")
    
    print(f"Loading image: {args.input}")
    image_tensor = preprocess_image(args.input)
    
    # Run inference
    print("Running inference...")
    top5, elapsed_ms = run_inference(model, image_tensor, device)
    
    # Prepare output
    output_data = {
        "model": args.model,
        "top5": top5,
        "elapsed_ms": round(elapsed_ms, 2),
        "device": device,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    
    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)
    
    print(f"✓ Inference complete!")
    print(f"  Elapsed: {elapsed_ms:.2f}ms")
    print(f"  Top prediction: {top5[0]['label']} ({top5[0]['probability']:.4f})")
    print(f"  Output written to: {args.output}")


if __name__ == "__main__":
    main()
