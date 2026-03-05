import io
import pydicom


def dicom_bytes_to_dataset(raw: bytes) -> pydicom.Dataset:
    return pydicom.dcmread(io.BytesIO(raw))


def dataset_to_bytes(ds: pydicom.Dataset) -> bytes:
    buf = io.BytesIO()
    pydicom.dcmwrite(buf, ds, write_like_original=False)
    return buf.getvalue()


def anonymize_dataset(ds: pydicom.Dataset) -> pydicom.Dataset:
    """
    Basic anonymization following DICOM PS3.15 Basic Application Level
    Confidentiality Profile. Replace with a vetted library (e.g.
    dicomanonymizer) for clinical production use.
    """
    tags_to_clear = [
        "PatientName", "PatientID", "PatientBirthDate", "PatientSex",
        "PatientAge", "PatientAddress", "PatientTelephoneNumbers",
        "ReferringPhysicianName", "InstitutionName", "InstitutionAddress",
        "StudyDescription", "SeriesDescription", "OperatorsName",
        "PerformingPhysicianName", "RequestingPhysician",
    ]
    for tag in tags_to_clear:
        if hasattr(ds, tag):
            setattr(ds, tag, "ANONYMIZED")
    return ds


def embed_examination_result(ds: pydicom.Dataset, result: str) -> pydicom.Dataset:
    """Inject examination result text into ImageComments (0020,4000)."""
    ds.ImageComments = result
    return ds