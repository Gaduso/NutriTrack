"""OpenFoodFacts product lookup by barcode (EAN/UPC).

Looks up a scanned barcode via the OpenFoodFacts v2 API and returns the product
name plus nutrition scaled to the package weight. OFF asks API clients to send a
descriptive User-Agent.
"""
import httpx
from fastapi import HTTPException

OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
OFF_FIELDS = "product_name,brands,quantity,product_quantity,nutriments"
USER_AGENT = "NutriTrack/1.0 (https://github.com/Gaduso/NutriTrack)"
DEFAULT_WEIGHT_G = 100.0


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def lookup_product(barcode: str) -> dict:
    barcode = (barcode or "").strip()
    if not barcode.isdigit():
        raise HTTPException(status_code=400, detail="Ungültiger Barcode.")

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(
                OFF_URL.format(barcode=barcode),
                params={"fields": OFF_FIELDS},
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail="OpenFoodFacts nicht erreichbar.")

    data = resp.json()
    if data.get("status") != 1 or not data.get("product"):
        raise HTTPException(
            status_code=404, detail="Produkt nicht gefunden (Barcode unbekannt)."
        )

    product = data["product"]
    nutriments = product.get("nutriments") or {}
    kcal_per_100g = _to_float(nutriments.get("energy-kcal_100g"))
    protein_per_100g = _to_float(nutriments.get("proteins_100g"))
    if kcal_per_100g is None and protein_per_100g is None:
        raise HTTPException(
            status_code=404, detail="Für dieses Produkt sind keine Nährwerte hinterlegt."
        )
    kcal_per_100g = kcal_per_100g or 0.0
    protein_per_100g = protein_per_100g or 0.0

    weight_g = _to_float(product.get("product_quantity"))
    if not weight_g or weight_g <= 0:
        weight_g = DEFAULT_WEIGHT_G

    name = (product.get("product_name") or "").strip() or "Unbekanntes Produkt"
    brand = (product.get("brands") or "").split(",")[0].strip()

    return {
        "barcode": barcode,
        "name": name,
        "brand": brand,
        "weight_g": round(weight_g, 1),
        "kcal_per_100g": round(kcal_per_100g, 1),
        "protein_per_100g": round(protein_per_100g, 1),
        "kcal": round(kcal_per_100g * weight_g / 100),
        "protein": round(protein_per_100g * weight_g / 100, 1),
    }
