import numpy as np
import torch
from torch.nn import (
    Sequential as Seq,
    Linear as Lin,
    ReLU,
    LeakyReLU,
    BatchNorm1d as BN,
    Dropout,
)
from torch_geometric.nn import (
    knn_interpolate,
    fps,
    radius,
    global_max_pool,
    global_mean_pool,
    knn,
)
from torch_geometric.data import Data
import torch_points as tp
import etw_pytorch_utils as pt_utils

from src.core.neighbourfinder import BaseMSNeighbourFinder
from src.core.base_conv import BaseConvolution
from src.core.common_modules import MLP

from src.utils.enums import ConvolutionFormat
from src.utils.model_building_utils.activation_resolver import get_activation

#################### THOSE MODULES IMPLEMENTS THE BASE DENSE CONV API ############################


class BaseDenseConvolutionDown(BaseConvolution):
    """ Multiscale convolution down (also supports single scale). Convolution kernel is shared accross the scales

        Arguments:
            sampler  -- Strategy for sampling the input clouds
            neighbour_finder -- Multiscale strategy for finding neighbours
    """

    CONV_TYPE = ConvolutionFormat.DENSE.value[-1]

    def __init__(self, sampler, neighbour_finder: BaseMSNeighbourFinder, *args, **kwargs):
        super(BaseDenseConvolutionDown, self).__init__(sampler, neighbour_finder, *args, **kwargs)
        self._index = kwargs.get("index", None)

    def conv(self, x, pos, new_pos, radius_idx, scale_idx):
        """ Implements a Dense convolution where radius_idx represents
        the indexes of the points in x and pos to be agragated into the new feature
        for each point in new_pos

        Arguments:
            x -- Previous features [B, C, N]
            pos -- Previous positions [B, N, 3]
            new_pos  -- Sampled positions [B, npoints, 3]
            radius_idx -- Indexes to group [B, npoints, nsample]
            scale_idx -- Scale index in multiscale convolutional layers
        """
        raise NotImplementedError

    def forward(self, data, **kwargs):
        """
        Arguments:
            x -- Previous features [B, C, N]
            pos -- Previous positions [B, N, 3]
        """
        x, pos = data.x, data.pos
        idx = self.sampler(pos)
        pos_flipped = pos.transpose(1, 2).contiguous()
        new_pos = tp.gather_operation(pos_flipped, idx).transpose(1, 2).contiguous()

        ms_x = []
        for scale_idx in range(self.neighbour_finder.num_scales):
            radius_idx = self.neighbour_finder(pos, new_pos, scale_idx=scale_idx)
            ms_x.append(self.conv(x, pos, new_pos, radius_idx, scale_idx))
        new_x = torch.cat(ms_x, 1)
        return Data(pos=new_pos, x=new_x)


class BaseDenseConvolutionUp(BaseConvolution):

    CONV_TYPE = ConvolutionFormat.DENSE.value[-1]

    def __init__(self, neighbour_finder, *args, **kwargs):
        super(BaseDenseConvolutionUp, self).__init__(None, neighbour_finder, *args, **kwargs)
        self._index = kwargs.get("index", None)
        self._skip = kwargs.get("skip", True)

    def conv(self, pos, pos_skip, x):
        raise NotImplementedError

    def forward(self, data, **kwargs):
        """ Propagates features from one layer to the next.
        data contains information from the down convs in data_skip

        Arguments:
            data -- (data, data_skip)
        """
        data, data_skip = data
        pos, x = data.pos, data.x
        pos_skip, x_skip = data_skip.pos, data_skip.x

        new_features = self.conv(pos, pos_skip, x)

        if x_skip is not None:
            new_features = torch.cat([new_features, x_skip], dim=1)  # (B, C2 + C1, n)

        new_features = new_features.unsqueeze(-1)

        if hasattr(self, "nn"):
            new_features = self.nn(new_features)

        return Data(x=new_features.squeeze(-1), pos=pos_skip)


class DenseFPModule(BaseDenseConvolutionUp):
    def __init__(self, up_conv_nn, bn=True, bias=False, activation="LeakyReLU", **kwargs):
        super(DenseFPModule, self).__init__(None, **kwargs)

        self.nn = pt_utils.SharedMLP(up_conv_nn, bn=bn, activation=get_activation(activation))

    def conv(self, pos, pos_skip, x):
        assert pos_skip.shape[2] == 3

        if pos is not None:
            dist, idx = tp.three_nn(pos_skip, pos)
            dist_recip = 1.0 / (dist + 1e-8)
            norm = torch.sum(dist_recip, dim=2, keepdim=True)
            weight = dist_recip / norm
            interpolated_feats = tp.three_interpolate(x, idx, weight)
        else:
            interpolated_feats = x.expand(*(x.size()[0:2] + (pos_skip.size(1),)))

        return interpolated_feats

    def __repr__(self):
        return "{}: {} ({})".format(self.__class__.__name__, self.nb_params, self.nn)


class GlobalDenseBaseModule(torch.nn.Module):
    def __init__(self, nn, aggr="max", bn=True, activation="LeakyReLU", **kwargs):
        super(GlobalDenseBaseModule, self).__init__()
        self.nn = pt_utils.SharedMLP(nn, bn=bn, activation=get_activation(activation))
        if aggr.lower() not in ["mean", "max"]:
            raise Exception("The aggregation provided is unrecognized {}".format(aggr))
        self._aggr = aggr.lower()

    @property
    def nb_params(self):
        """[This property is used to return the number of trainable parameters for a given layer]
        It is useful for debugging and reproducibility.
        Returns:
            [type] -- [description]
        """
        model_parameters = filter(lambda p: p.requires_grad, self.parameters())
        self._nb_params = sum([np.prod(p.size()) for p in model_parameters])
        return self._nb_params

    def forward(self, data, **kwargs):
        x, pos = data.x, data.pos
        pos_flipped = pos.transpose(1, 2).contiguous()

        x = self.nn(torch.cat([x, pos_flipped], dim=1).unsqueeze(-1))

        if self._aggr == "max":
            x = x.squeeze(-1).max(-1)[0]
        elif self._aggr == "mean":
            x = x.squeeze(-1).mean(-1)
        else:
            raise NotImplementedError("The following aggregation {} is not recognized".format(self._aggr))

        pos = None  # pos.mean(1).unsqueeze(1)
        x = x.unsqueeze(-1)
        return Data(x=x, pos=pos)

    def __repr__(self):
        return "{}: {} (aggr={}, {})".format(self.__class__.__name__, self.nb_params, self._aggr, self.nn)
