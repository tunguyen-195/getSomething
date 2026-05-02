import torch
print(torch.cuda.is_available())      # Kỳ vọng: True
print(torch.version.cuda)             # Kỳ vọng: 12.1
print(torch.backends.cudnn.version()) # Kỳ vọng: ra số version (ví dụ: 8905)