import numpy as np
from typing import Any, Dict, Union, Tuple
import rasterio
import rasterio.windows
from georeader import window_utils

try:
    import torch
    import torch.nn.functional
    Tensor = Union[torch.Tensor, np.ndarray]
    torch_installed = True
except ImportError:
    Tensor =np.ndarray
    torch_installed = False



class GeoTensor:
    def __init__(self, values:Tensor,
                 transform:rasterio.Affine, crs:Any,
                 fill_value_default:Union[int, float]=0):
        self.values = values
        self.transform = transform
        self.crs = crs
        self.fill_value_default = fill_value_default
        shape = self.shape
        if (len(shape) < 2) or (len(shape) > 4):
            raise ValueError(f"Expected 2d-4d array found {shape}")

    @property
    def dims(self) -> Tuple:
        # TODO for the future allow different ordering of dimensions
        shape = self.shape
        if len(shape) == 2:
            dims = ("y", "x")
        elif len(shape) == 3:
            dims = ("band", "y", "x")
        elif len(shape) == 4:
            dims = ("time", "band", "y", "x")
        else:
            raise ValueError(f"Unexpected 2d-4d array found {shape}")
        
        return dims

    @property
    def shape(self) -> Tuple:
        return tuple(self.values.shape)

    @property
    def resolution(self) -> Tuple[float, float]:
        return abs(self.transform.a), abs(self.transform.e)

    @property
    def dtype(self):
        return self.values.dtype

    @property
    def height(self) -> int:
        return self.shape[-2]

    @property
    def width(self) -> int:
        return self.shape[-1]

    @property
    def count(self) -> int:
        return self.shape[-3]

    @property
    def bounds(self) -> Tuple[float, float, float, float]:
        return rasterio.windows.bounds(rasterio.windows.Window(row_off=0, col_off=0, height=self.height, width=self.width),
                                       self.transform)

    @property
    def attrs(self) -> Dict[str, Any]:
        return vars(self)

    def load(self) -> '__class__':
        return self

    def __copy__(self) -> '__class__':
        return GeoTensor(self.values.copy(), self.transform, self.crs, self.fill_value_default)

    def isel(self, sel: Dict[str, slice]) -> '__class__':
        """
        Slicing with dict. It doesn't work with negative indexes!

        Args:
            sel: Dict with slice selection; i.e. `{"x": slice(10, 20), "y": slice(20, 340)}`.

        Returns:

        """
        for k in sel:
            if k not in self.dims:
                raise NotImplementedError(f"Axis {k} not in {self.dims}")

        slice_list = self._slice_tuple(sel)

        slices_window = []
        for k in ["y", "x"]:
            if k in sel:
                slices_window.append(sel[k])
            else:
                size = self.width if (k == "x") else self.height
                slices_window.append(slice(0, size))

        window_current = rasterio.windows.Window.from_slices(*slices_window, boundless=False) # if negative it will complain

        transform_current = rasterio.windows.transform(window_current, transform=self.transform)

        return GeoTensor(self.values[slice_list], transform_current, self.crs,
                         self.fill_value_default)

    def _slice_tuple(self, sel):
        slice_list = []
        # shape_ = self.shape
        # sel_copy = sel.copy()
        for _i, k in enumerate(self.dims):
            if k in sel:
                # sel_copy[k] = slice(max(0, sel_copy[k].start), min(shape_[_i], sel_copy[k].stop))
                slice_list.append(sel[k])
            else:
                slice_list.append(slice(None))
        return tuple(slice_list)

    def __repr__(self)->str:
        return f""" 
         Transform: {self.transform}
         Shape: {self.shape}
         Resolution: {self.resolution}
         Bounds: {self.bounds}
         CRS: {self.crs}
         fill_value_default: {self.fill_value_default}
        """

    def pad(self, pad_width=Dict[str, Tuple[int, int]], mode:str="constant",
            constant_values:Any=0)-> '__class__':
        """

        Args:
            pad_width: e.g. `{"x": (pad_x_0, pad_x_1), "y": (pad_y_0, pad_y_1)}`
            mode:
            constant_values:

        Returns:

        """

        # Pad the data
        pad_torch = False
        if torch_installed:
            if isinstance(self.values, torch.Tensor):
                pad_torch = True

        if pad_torch:
            pad_list_torch = []
            for k in reversed(self.dims):
                if k in pad_width:
                    pad_list_torch.extend(list(pad_width[k]))
                else:
                    pad_list_torch.extend([0,0])
            values_new = torch.nn.functional.pad(self.values, tuple(pad_list_torch), mode=mode,
                                                 value=constant_values)
        else:
            pad_list_np = []
            for k in self.dims:
                if k in pad_width:
                    pad_list_np.append(pad_width[k])
                else:
                    pad_list_np.append((0,0))
            values_new = np.pad(self.values, tuple(pad_list_np), mode=mode,
                                constant_values=constant_values)

        # Compute the new transform
        slices_window = []
        for k in ["y", "x"]:
            size = self.width if (k == "x") else self.height
            if k in pad_width:
                slices_window.append(slice(-pad_width[k][0], size+pad_width[k][1]))
            else:
                slices_window.append(slice(0, size))

        window_current = rasterio.windows.Window.from_slices(*slices_window, boundless=True)
        transform_current = rasterio.windows.transform(window_current, transform=self.transform)
        return GeoTensor(values_new, transform_current, self.crs,
                         self.fill_value_default)

    def read_from_window(self, window:rasterio.windows.Window, boundless:bool=True) -> '__class__':
        """

        Args:
            window:
            boundless:

        Returns:

        Raises:
            rasterio.windows.WindowError if `window` does not intersect the data

        """

        window_data = rasterio.windows.Window(col_off=0, row_off=0,
                                              width=self.width, height=self.height)
        if boundless:
            slice_dict, pad_width = window_utils.get_slice_pad(window_data, window)
            need_pad = any(p != 0 for p in pad_width["x"] + pad_width["y"])
            X_sliced = self.isel(slice_dict)
            if need_pad:
                X_sliced = X_sliced.pad(pad_width=pad_width, mode="constant",
                                        constant_values=self.fill_value_default)
            return X_sliced
        else:
            window_read = rasterio.windows.intersection(window, window_data)
            slice_y, slice_x = window_read.toslices()
            slice_dict = {"x": slice_x, "y": slice_y}
            slices_ = self._slice_tuple(slice_dict)
            transform_current = rasterio.windows.transform(window_read, transform=self.transform)
            return GeoTensor(self.values[slices_], transform_current, self.crs,
                             self.fill_value_default)







