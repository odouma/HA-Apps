"""
Beheert geüploade afbeeldingen voor de PDF-opmaak. In tegenstelling tot het
oude, ene gedeelde logo kunnen hier meerdere afbeeldingen worden opgeslagen;
elk "afbeelding"-element in de PDF-opmaak verwijst naar een specifieke
afbeelding via zijn image_id.
"""
import json
import os
import uuid

IMAGES_DIR = "/data/images"
REGISTRY_FILE = os.path.join(IMAGES_DIR, "registry.json")

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def _load_registry():
    if not os.path.exists(REGISTRY_FILE):
        return {}
    try:
        with open(REGISTRY_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_registry(registry):
    os.makedirs(IMAGES_DIR, exist_ok=True)
    with open(REGISTRY_FILE, "w") as f:
        json.dump(registry, f, indent=2)


def list_images():
    registry = _load_registry()
    return [
        {"id": image_id, "filename": info.get("filename", image_id)}
        for image_id, info in sorted(registry.items(), key=lambda kv: kv[1].get("filename", ""))
    ]


def save_image(file_storage):
    """Slaat een geüploade afbeelding op en registreert die. Retourneert
    het nieuwe image-id."""
    original_name = file_storage.filename or "afbeelding"
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".png"

    image_id = uuid.uuid4().hex
    os.makedirs(IMAGES_DIR, exist_ok=True)
    file_storage.save(os.path.join(IMAGES_DIR, image_id + ext))

    registry = _load_registry()
    registry[image_id] = {"filename": original_name, "ext": ext}
    _save_registry(registry)
    return image_id


def delete_image(image_id):
    registry = _load_registry()
    info = registry.pop(image_id, None)
    if info is None:
        return False
    path = os.path.join(IMAGES_DIR, image_id + info["ext"])
    if os.path.exists(path):
        os.remove(path)
    _save_registry(registry)
    return True


def image_path(image_id):
    if not image_id:
        return None
    registry = _load_registry()
    info = registry.get(image_id)
    if not info:
        return None
    path = os.path.join(IMAGES_DIR, image_id + info["ext"])
    return path if os.path.exists(path) else None


def import_legacy_logo(logo_file_path):
    """Migreert het oude, ene gedeelde logo.png (van vóór afbeeldingen per
    element) naar het nieuwe register, zodat een bestaande PDF-opmaak niet
    plots leeg komt te staan. Gebeurt alleen als er nog geen andere
    afbeeldingen geregistreerd zijn."""
    registry = _load_registry()
    if registry or not logo_file_path or not os.path.exists(logo_file_path):
        return None

    image_id = "legacy_logo"
    os.makedirs(IMAGES_DIR, exist_ok=True)
    dest = os.path.join(IMAGES_DIR, image_id + ".png")
    with open(logo_file_path, "rb") as src, open(dest, "wb") as dst:
        dst.write(src.read())

    registry[image_id] = {"filename": "logo.png", "ext": ".png"}
    _save_registry(registry)
    return image_id
