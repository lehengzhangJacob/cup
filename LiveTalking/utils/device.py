import os
import torch

def initialize_device():
    if os.getenv("LIVETALKING_CPU_STANDBY", "false").lower() in {
        "1",
        "true",
        "yes",
    }:
        return torch.device('cpu')
    if torch.cuda.is_available():
        return torch.device('cuda')
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device('mps')
    else:
        return torch.device('cpu')
