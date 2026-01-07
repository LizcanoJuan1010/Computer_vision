# Face Recognition Storage Structure

This directory stores facial images organized by category for training and reference.

## Directory Structure

```
faces/
├── known/          # Authorized persons (employees, residents, etc.)
├── blacklist/      # Unauthorized persons (trespassers, banned individuals)
└── unknown/        # Unclassified faces (for review and classification)
```

## Organization Structure

Within each category, images are organized by organization:

```
faces/known/{org_slug}/{person_id}/
    ├── face_001.jpg
    ├── face_002.jpg
    └── face_003.jpg
```

## File Naming Convention

- Format: `{timestamp}_{face_id}.jpg`
- Example: `2025-12-23_14-30-45_12345.jpg`

## Storage Guidelines

### Known Faces
- Minimum 3-5 images per person for better recognition
- Images should show different angles (frontal, profile)
- Different lighting conditions recommended
- Update images periodically (every 6-12 months)

### Blacklist Faces
- At least 1 clear frontal image required
- Additional images improve detection accuracy
- Log entry date and reason for blacklisting
- Review blacklist quarterly for expired entries

### Unknown Faces
- Temporary storage for faces detected but not in database
- Reviewed periodically by operators
- Moved to known/blacklist after classification
- Auto-purge after 30 days if not classified

## Integration with InsightFace

This structure is designed to work with InsightFace model training:

1. **Initial Training**: Load all images from `known/` and `blacklist/`
2. **Embedding Extraction**: Generate 512-dim embeddings for each image
3. **Database Storage**: Store embeddings in PostgreSQL with pgvector
4. **Re-training**: Periodic re-training when new faces added (weekly/monthly)

## Usage Example

```python
from pathlib import Path

# Get path for new known face
org_slug = "acme-corp"
person_id = "12345"
category = "known"

face_dir = Path(f"/evidence/faces/{category}/{org_slug}/{person_id}")
face_dir.mkdir(parents=True, exist_ok=True)

# Save image
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
image_path = face_dir / f"{timestamp}_{person_id}.jpg"
cv2.imwrite(str(image_path), face_image)
```

## Backup and Security

- **Backup**: Daily backups to S3/MinIO recommended
- **Access Control**: Restricted to inference service and admin users
- **GDPR Compliance**: Faces are personal data - ensure proper consent and retention policies
- **Encryption**: Consider encrypting at rest for sensitive deployments

## Performance Considerations

- **Image Size**: Store at 256x256 or 512x512 for optimal recognition
- **Format**: JPEG with 90% quality (balance size vs accuracy)
- **Indexing**: Use FAISS for fast similarity search with >1000 identities
- **Cache**: Keep embeddings in memory (Redis) for real-time inference

## Monitoring

Track the following metrics:
- Number of faces per category per organization
- Storage usage (GB)
- Recognition accuracy by category
- False positive/negative rates

---

**Last Updated**: 2025-12-23
**Version**: 1.0.0
