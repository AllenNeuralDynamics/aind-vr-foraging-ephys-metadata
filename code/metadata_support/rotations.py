from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Tuple, Union

import numpy as np


AxesConvention = Literal["rows", "cols"]
EulerOrder = Literal["xyz"]            # extend later
EulerFrame = Literal["global"]         # extend later
BodyAxis = Literal["x", "y", "z"]


# ----------------------------
# Small value / validation utils
# ----------------------------

def _as_R(R: np.ndarray) -> np.ndarray:
    R = np.asarray(R, dtype=float)
    if R.shape != (3, 3):
        raise ValueError(f"R must be shape (3,3); got {R.shape}")
    return R

def _as_T(T: np.ndarray) -> np.ndarray:
    T = np.asarray(T, dtype=float)
    if T.shape != (4, 4):
        raise ValueError(f"T must be shape (4,4); got {T.shape}")
    return T

def _validate_rotation_matrix(R: np.ndarray, tol: float = 1e-6) -> None:
    """
    Validate that R is a proper rotation matrix (orthonormal with det ~ +1).
    """
    R = _as_R(R)
    I = np.eye(3)
    err_ortho = np.linalg.norm(R.T @ R - I, ord="fro")
    det = np.linalg.det(R)
    if err_ortho > tol or not np.isfinite(det) or abs(det - 1.0) > 1e-4:
        raise ValueError(
            f"R is not a valid rotation matrix: ||R^T R - I||_F={err_ortho:.3e}, det={det:.6f}"
        )

def _to_cols_axes(R: np.ndarray, axes: AxesConvention) -> np.ndarray:
    """
    Convert an input rotation matrix into the 'cols-as-axes' convention.

    - axes="cols": columns are body axes expressed in world coords.
      Common robotics "active rotation": v_world = R_cols @ v_body

    - axes="rows": rows are body axes expressed in world coords.
      Then R_rows = R_cols.T, and v_body = R_rows @ v_world.
    """
    R = _as_R(R)
    if axes == "cols":
        return R
    if axes == "rows":
        return R.T
    raise ValueError(f"Unknown axes convention: {axes}")

def _from_cols_axes(R_cols: np.ndarray, axes: AxesConvention) -> np.ndarray:
    R_cols = _as_R(R_cols)
    if axes == "cols":
        return R_cols
    if axes == "rows":
        return R_cols.T
    raise ValueError(f"Unknown axes convention: {axes}")

def _body_axis_vector_world(R: np.ndarray, axis: BodyAxis, axes: AxesConvention) -> np.ndarray:
    """
    Return the chosen body axis (x/y/z) expressed in world coordinates.

    For axes="cols": axis vector is the corresponding column.
    For axes="rows": axis vector is the corresponding row.
    """
    R = _as_R(R)
    idx = {"x": 0, "y": 1, "z": 2}[axis]
    if axes == "cols":
        v = R[:, idx]
    elif axes == "rows":
        v = R[idx, :]
    else:
        raise ValueError(f"Unknown axes convention: {axes}")
    return np.asarray(v, dtype=float)


# ----------------------------
# Euler (3-DOF) API
# ----------------------------

def euler_deg_from_R(
    R: np.ndarray,
    order: EulerOrder = "xyz",
    frame: EulerFrame = "global",
    axes: AxesConvention = "rows",
    validate: bool = True,
) -> np.ndarray:
    """
    Extract Euler angles [x, y, z] in degrees from a rotation matrix.

    Implemented convention (matches your existing `euler_globalXYZ_from_R`):
      - order="xyz", frame="global"
      - R_cols = Rz(z) @ Ry(y) @ Rx(x)

    Notes:
      - Internally we convert to cols-as-axes (R_cols) to apply the formulas.
      - If you pass axes="rows", we transpose before extracting.
    """
    if order != "xyz" or frame != "global":
        raise NotImplementedError(f"Only order='xyz', frame='global' implemented (got {order=}, {frame=}).")

    R_in = _as_R(R)
    if validate:
        _validate_rotation_matrix(R_in)

    R_cols = _to_cols_axes(R_in, axes)

    # Your original formulas (in radians)
    x = np.arctan2(R_cols[2, 1], R_cols[2, 2])
    y = -np.arcsin(np.clip(R_cols[2, 0], -1.0, 1.0))
    z = np.arctan2(R_cols[1, 0], R_cols[0, 0])

    return np.degrees([x, y, z])


def R_from_euler_deg(
    angles_deg: Tuple[float, float, float],
    order: EulerOrder = "xyz",
    frame: EulerFrame = "global",
    axes: AxesConvention = "rows",
) -> np.ndarray:
    """
    Construct a rotation matrix from Euler angles [x, y, z] in degrees.

    Implemented convention:
      - order="xyz", frame="global"
      - R_cols = Rz(z) @ Ry(y) @ Rx(x)
    """
    if order != "xyz" or frame != "global":
        raise NotImplementedError(f"Only order='xyz', frame='global' implemented (got {order=}, {frame=}).")

    x_deg, y_deg, z_deg = angles_deg
    x = np.deg2rad(x_deg)
    y = np.deg2rad(y_deg)
    z = np.deg2rad(z_deg)

    cx, sx = np.cos(x), np.sin(x)
    cy, sy = np.cos(y), np.sin(y)
    cz, sz = np.cos(z), np.sin(z)

    Rx = np.array([[1, 0, 0],
                   [0, cx, -sx],
                   [0, sx, cx]], dtype=float)

    Ry = np.array([[cy, 0, sy],
                   [0, 1, 0],
                   [-sy, 0, cy]], dtype=float)

    Rz = np.array([[cz, -sz, 0],
                   [sz, cz, 0],
                   [0, 0, 1]], dtype=float)

    R_cols = Rz @ Ry @ Rx
    return _from_cols_axes(R_cols, axes)


def euler_deg_from_T(T: np.ndarray, **kwargs) -> np.ndarray:
    """Convenience wrapper: extract Euler angles from a 4x4 transform."""
    T = _as_T(T)
    return euler_deg_from_R(T[:3, :3], **kwargs)


def T_from_R(R: np.ndarray, t: Optional[np.ndarray] = None) -> np.ndarray:
    """Convenience: make a 4x4 transform from R (and optional translation t)."""
    R = _as_R(R)
    if t is None:
        t = np.zeros(3, dtype=float)
    t = np.asarray(t, dtype=float).reshape(3)
    T = np.eye(4, dtype=float)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


# ----------------------------
# Tilt (2-DOF) API (your rx, ry)
# ----------------------------

def tilt_rx_ry_deg_from_R(
    R: np.ndarray,
    axis: BodyAxis = "z",
    axes: AxesConvention = "rows",
    up_hint: np.ndarray = np.array([0.0, 0.0, 1.0]),
    force_up: bool = True,
    validate: bool = True,
) -> Tuple[float, float]:
    """
    Extract (rx, ry) tilt angles (degrees) from the direction of a chosen body axis (default: body z-axis)
    expressed in world coordinates.

    This representation is 2-DOF: it captures the axis direction and discards yaw about that axis.

    Conventions (matches your existing rx/ry ↔ z-axis math):
      Given unit axis direction n = [nx, ny, nz],
        rx = asin(ny)                  (deg)
        ry = atan2(nx, nz)             (deg)

      Inverse:
        ny = sin(rx)
        nx = cos(rx) * sin(ry)
        nz = cos(rx) * cos(ry)

    If force_up=True, we flip the axis direction to have positive dot with up_hint.
    """
    R_in = _as_R(R)
    if validate:
        _validate_rotation_matrix(R_in)

    v = _body_axis_vector_world(R_in, axis=axis, axes=axes)
    up = np.asarray(up_hint, dtype=float).reshape(3)
    if force_up and np.dot(v, up) < 0:
        v = -v

    nv = v / np.linalg.norm(v)

    rx = np.arcsin(np.clip(nv[1], -1.0, 1.0))
    ry = np.arctan2(nv[0], nv[2])

    return float(np.degrees(rx)), float(np.degrees(ry))


def axis_from_tilt_rx_ry_deg(rx_ry_deg: Tuple[float, float]) -> np.ndarray:
    """
    Convert (rx, ry) in degrees to the corresponding unit axis direction n = [nx, ny, nz].
    """
    rx_deg, ry_deg = rx_ry_deg
    rx = np.deg2rad(rx_deg)
    ry = np.deg2rad(ry_deg)

    ny = np.sin(rx)
    nx = np.cos(rx) * np.sin(ry)
    nz = np.cos(rx) * np.cos(ry)

    n = np.array([nx, ny, nz], dtype=float)
    return n / np.linalg.norm(n)


def R_from_tilt_rx_ry_deg(
    rx_ry_deg: Tuple[float, float],
    axis: BodyAxis = "z",
    axes: AxesConvention = "rows",
    yaw_reference: np.ndarray = np.array([1.0, 0.0, 0.0]),
) -> np.ndarray:
    """
    Construct a full 3x3 rotation matrix from a 2-DOF tilt (rx, ry) by choosing yaw using a reference vector.

    Steps:
      1) Compute desired body axis direction (default: body z) in world coords.
      2) Choose an orthonormal frame (x,y,z) around that axis by aligning x as closely as possible
         with yaw_reference (projected to the plane orthogonal to z).

    Notes:
      - If yaw_reference is nearly parallel to z, we fall back to another reference.
      - axis parameter currently supports 'z' best; for 'x'/'y' we rotate labels accordingly.
    """
    z = axis_from_tilt_rx_ry_deg(rx_ry_deg)  # this is the *desired axis direction* in world coords

    ref = np.asarray(yaw_reference, dtype=float).reshape(3)
    ref = ref / (np.linalg.norm(ref) + 1e-15)

    # If ref ~ parallel to z, pick a safer fallback
    if abs(np.dot(z, ref)) > 0.99:
        ref = np.array([0.0, 1.0, 0.0], dtype=float)
        if abs(np.dot(z, ref)) > 0.99:
            ref = np.array([0.0, 0.0, 1.0], dtype=float)

    # Build x perpendicular to z, guided by ref
    x = np.cross(ref, z)
    nx = np.linalg.norm(x)
    if nx < 1e-12:
        raise ValueError("Could not construct frame: yaw_reference is effectively parallel to tilt axis.")
    x /= nx

    y = np.cross(z, x)

    # Now assign these to the requested body axis.
    # We have constructed a frame where body 'z' maps to z (world).
    # If user requests axis != 'z', we permute accordingly.
    if axis == "z":
        ax_w, ay_w, az_w = x, y, z
    elif axis == "x":
        # Want body x-axis to point along z (computed). Build remaining axes:
        # rename: ax=z, choose ay=x, az=y (right-handed)
        ax_w, ay_w, az_w = z, x, y
    elif axis == "y":
        # rename: ay=z, choose az=x, ax=y (right-handed)
        ax_w, ay_w, az_w = y, z, x
    else:
        raise ValueError(f"Unknown axis: {axis}")

    if axes == "rows":
        # rows are body axes in world coords
        R_out = np.vstack([ax_w, ay_w, az_w])
    elif axes == "cols":
        # columns are body axes in world coords
        R_out = np.column_stack([ax_w, ay_w, az_w])
    else:
        raise ValueError(f"Unknown axes convention: {axes}")

    return R_out


def tilt_rx_ry_deg_from_T(T: np.ndarray, **kwargs) -> Tuple[float, float]:
    """Convenience wrapper: extract tilt from a 4x4 transform."""
    T = _as_T(T)
    return tilt_rx_ry_deg_from_R(T[:3, :3], **kwargs)


def T_from_R_t(
    R: np.ndarray,
    t: np.ndarray,
) -> np.ndarray:
    """
    Construct a 4x4 homogeneous transformation matrix from a rotation matrix
    and translation vector.

    Parameters
    ----------
    R : np.ndarray, shape (3, 3)
        Rotation matrix. Must be orthonormal with det ~= +1.
    t : np.ndarray, shape (3,)
        Translation vector, expressed in the same coordinate frame as R.

    Returns
    -------
    T : np.ndarray, shape (4, 4)
        Homogeneous transform:

            [ R  t ]
            [ 0  1 ]

    Notes
    -----
    - Rotation conventions (rows-vs-cols) are inherited from R directly.
      This function does *not* reinterpret R.
    - This represents an affine transform acting on homogeneous coordinates:

          x_world = T @ [x_local; 1]

      if R and t are defined in that sense.
    """
    R = _as_R(R)
    t = np.asarray(t, dtype=float).reshape(3)

    T = np.eye(4, dtype=float)
    T[:3, :3] = R
    T[:3, 3] = t

    return T