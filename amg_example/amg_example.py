import numpy as np
import torch
import matplotlib.pyplot as plt
import cv2
import torch.utils.benchmark as benchmark

def profiler_runner(path, fn, *args, **kwargs):
    with torch.profiler.profile(
            activities=[torch.profiler.ProfilerActivity.CPU,
                        torch.profiler.ProfilerActivity.CUDA],
            record_shapes=True) as prof:
        result = fn(*args, **kwargs)
    print(f"Saving trace under {path}")
    prof.export_chrome_trace(path)
    return result

def show_anns(anns):
    if len(anns) == 0:
        return
    sorted_anns = sorted(anns, key=(lambda x: x['area']), reverse=True)
    ax = plt.gca()
    ax.set_autoscale_on(False)

    img = np.ones((sorted_anns[0]['segmentation'].shape[0], sorted_anns[0]['segmentation'].shape[1], 4))
    img[:,:,3] = 0
    for ann in sorted_anns:
        m = ann['segmentation']
        color_mask = np.concatenate([np.random.random(3), [0.35]])
        img[m] = color_mask
    ax.imshow(img)

def _apply_eval_dtype_sam(model, dtype):

    def prep_model(model, dtype):
        if dtype is not None:
            return model.eval().to(dtype)
        return model.eval()

    model.image_encoder = prep_model(model.image_encoder, dtype)
    model.sam_prompt_encoder = prep_model(model.sam_prompt_encoder, dtype)
    model.sam_mask_decoder = prep_model(model.sam_mask_decoder, dtype)

    return model

image = cv2.imread('dog.jpg')
image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


# from segment_anything_fast import sam_model_registry, sam_model_fast_registry, SamAutomaticMaskGenerator
# 
# sam_checkpoint = "checkpoints/sam_vit_h_4b8939.pth"
# model_type = "vit_h"
device = "cuda"
# 
# sam = sam_model_fast_registry[model_type](checkpoint=sam_checkpoint)
# sam.to(device=device)

from sam2.build_sam import build_sam2
from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator

sam2_checkpoint = "checkpoints/sam2_hiera_large.pt"
model_cfg = "sam2_hiera_l.yaml"

sam2 = build_sam2(model_cfg, sam2_checkpoint, device=device, apply_postprocessing=False)
sam2 = _apply_eval_dtype_sam(sam2, torch.float32)
sam2.to(device=device)

mask_generator = SAM2AutomaticMaskGenerator(sam2)

# Important to enable CUDA graphs
with torch.no_grad():
    # Run thrice for warmup
    masks = mask_generator.generate(image)
    masks = mask_generator.generate(image)
    masks = mask_generator.generate(image)
    
    # Save an example
    plt.figure(figsize=(image.shape[1]/100., image.shape[0]/100.), dpi=100)
    plt.imshow(image)
    show_anns(masks)
    plt.axis('off')
    plt.tight_layout()
    plt.savefig('dog_mask_fast.png', format='png')
    
    # Benchmark
    torch.cuda.synchronize()
    start_event = torch.cuda.Event(enable_timing=True)
    end_event = torch.cuda.Event(enable_timing=True)
    start_event.record()
    for _ in range(10):
        masks = mask_generator.generate(image)
    end_event.record()
    torch.cuda.synchronize()
    print(start_event.elapsed_time(end_event) / 10.)
    
    # Save a GPU trace
    profiler_runner(f"amg_example_trace.json.gz", mask_generator.generate, image)
    
    # Write out memory usage
    max_memory_allocated_bytes = torch.cuda.max_memory_allocated()
    _, total_memory = torch.cuda.mem_get_info()
    max_memory_allocated_percentage = int(100 * (max_memory_allocated_bytes / total_memory))
    max_memory_allocated_bytes = max_memory_allocated_bytes >> 20
    print(f"memory(MiB): {max_memory_allocated_bytes} memory(%): {max_memory_allocated_percentage}")
