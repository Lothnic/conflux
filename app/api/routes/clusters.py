"""
Cluster-related endpoints.
"""

from fastapi import APIRouter, HTTPException

from app.core.database import database_available, init_db_sync
from app.services.cluster_service import fetch_latest_clusters

router = APIRouter()


@router.get("/clusters")
async def get_clusters(limit: int = 50):
    """Return latest cluster summaries from the DB."""
    init_db_sync()
    try:
        clusters = fetch_latest_clusters(limit)
        return {"clusters": clusters}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/clusters/geojson")
async def get_clusters_geojson(limit: int = 200):
    """Return cluster centroids as GeoJSON FeatureCollection."""
    init_db_sync()
    try:
        clusters = fetch_latest_clusters(limit)
        features = []
        for c in clusters:
            lat = c.get("centroid_lat")
            lng = c.get("centroid_lng")
            if lat is None or lng is None:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lng, lat]},
                    "properties": {
                        "cluster_id": c.get("cluster_id"),
                        "size": c.get("size"),
                        "keywords": c.get("keywords"),
                        "created_at": c.get("created_at"),
                        "location_confidence": c.get("location_confidence"),
                        "location_precision_meters": c.get("location_precision_meters"),
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
