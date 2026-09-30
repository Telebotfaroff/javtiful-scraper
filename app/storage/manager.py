from pathlib import Path
class StorageManager:
    def __init__(self,root="tmp"): self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
    def path(self,name): return self.root/name
