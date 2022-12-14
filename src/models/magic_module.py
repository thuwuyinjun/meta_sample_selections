import torch.nn as nn
from torch.nn import functional as F
from torch.nn.modules.utils import _pair

from pytorch_pretrained_bert.modeling import BertSelfAttention

import operator
import copy


class MagicModule(nn.Module):
    def __init__(self, module):
        nn.Module.__init__(self)
        self._type = type(module)

        for key, value in module._parameters.items():
            if value is not None:
                self.register_parameter('_origin_' + key, value)
                self.register_buffer(key, value.data)
            else:
                self.register_buffer(key, None)

        for key, value in module._buffers.items():
            self.register_buffer(key, copy.deepcopy(value))

        for key, value in module._modules.items():
            self.add_module(key, MagicModule(value))

        for key, value in module.__dict__.items():
            if (not key in self.__dict__) and\
                    (not key in self._buffers) and\
                    (not key in self._modules):
                self.__setattr__(key, value)

    def forward(self, *args, **kwargs):
        return self._type.forward(self, *args, **kwargs)

    def update_params(self, deltas):
        sub_params = {}
        for key, delta in deltas.items():
            if not ('.' in key):
                self._buffers[key] = self._buffers[key] + delta
            else:
                attr = key.split('.')[0]
                if not (attr in sub_params):
                    sub_params[attr] = {}
                sub_params[attr]['.'.join(key.split('.')[1:])] = delta
            del delta
        for key, value in sub_params.items():
            self._modules[key].update_params(value)
            del value


    def check_forward_args(self, *args, **kwargs):
        assert issubclass(self._type, nn.RNNBase)
        return nn.RNNBase.check_forward_args(self, *args, **kwargs)

    @property
    def _flat_weights(self):
        assert issubclass(self._type, nn.RNNBase)
        return [p for layerparams in self.all_weights for p in layerparams]

    @property
    def all_weights(self):
        assert issubclass(self._type, nn.RNNBase)
        return [[getattr(self, weight) for weight in weights] for weights in
                self._all_weights]

    def _get_abs_string_index(self, idx):
        assert issubclass(self._type, nn.ModuleList) or issubclass(self._type, nn.Sequential)
        """Get the absolute index for the list of modules"""
        idx = operator.index(idx)
        if not (-len(self) <= idx < len(self)):
            raise IndexError('index {} is out of range'.format(idx))
        if idx < 0:
            idx += len(self)
        return str(idx)

    def __getitem__(self, idx):
        assert issubclass(self._type, nn.ModuleList) or issubclass(self._type, nn.Sequential)
        if isinstance(idx, slice):
            return self.__class__(list(self._modules.values())[idx])
        else:
            return self._modules[self._get_abs_string_index(idx)]

    def __len__(self):
        assert issubclass(self._type, nn.ModuleList) or issubclass(self._type, nn.Sequential)
        return len(self._modules)

    def transpose_for_scores(self, x):
        assert issubclass(self._type, BertSelfAttention)
        new_x_shape = x.size()[:-1] + (
            self.num_attention_heads, self.attention_head_size)
        x = x.view(*new_x_shape)
        return x.permute(0, 2, 1, 3)

    # def conv2d_forward(self, input, weight):
    def _conv_forward(self, input, weight, bias):
        assert issubclass(self._type, nn.Conv2d)

        if self.padding_mode == 'circular':
            expanded_padding = ((self.padding[1] + 1) // 2, self.padding[1] // 2,
                                (self.padding[0] + 1) // 2, self.padding[0] // 2)
            return F.conv2d(F.pad(input, expanded_padding, mode='circular'),
                            weight, bias, self.stride,
                            _pair(0), self.dilation, self.groups)
        return F.conv2d(input, weight, bias, self.stride,
                        self.padding, self.dilation, self.groups)

    def _check_input_dim(self, input):
        assert issubclass(self._type, nn.BatchNorm2d)
        if input.dim() != 4:
            raise ValueError('expected 4D input (got {}D input)'
                             .format(input.dim()))