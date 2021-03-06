import unittest
from omegaconf import OmegaConf
import os
import sys
from glob import glob
import torch

DIR = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.join(DIR, "..")
sys.path.insert(0, ROOT)

from test.mockdatasets import MockDatasetGeometric


from src import instantiate_model
from src.utils.model_building_utils.model_definition_resolver import resolve_model
from src.utils.config import set_format

# calls resolve_model, then find_model_using_name

seed = 0
torch.manual_seed(seed)


def _find_model_using_name(model_class, task, model_config, dataset):
    resolve_model(model_config, dataset, task)
    return instantiate_model(model_class, task, model_config, dataset)


def load_model_config(task, model_type):
    models_conf = os.path.join(ROOT, "conf/models/{}/{}.yaml".format(task, model_type))
    config = OmegaConf.load(models_conf)
    return config.models


class TestModelUtils(unittest.TestCase):
    def setUp(self):
        self.data_config = OmegaConf.load(os.path.join(DIR, "test_config/data_config.yaml"))
        self.model_type_files = glob(os.path.join(ROOT, "conf/models/*/*.yaml"))

    def test_createall(self):
        for type_file in self.model_type_files:

            associated_task = type_file.split("/")[-2]
            models_config = OmegaConf.load(type_file).models
            for model_name in models_config.keys():
                print(model_name)
                if model_name not in ["MyTemplateModel"]:
                    model_config = models_config[model_name]
                    model_class = getattr(model_config, "class")
                    model_config = OmegaConf.merge(model_config, self.data_config)
                    _find_model_using_name(model_class, associated_task, model_config, MockDatasetGeometric(6))

    def test_pointnet2(self):
        params = load_model_config("segmentation", "pointnet2")["pointnet2"]
        model_class = getattr(params, "class")
        model_config = OmegaConf.merge(params, self.data_config)
        dataset = MockDatasetGeometric(5)
        model = _find_model_using_name(model_class, "segmentation", model_config, dataset)
        model.set_input(dataset[0])
        model.forward()
        model.backward()

    def test_kpconv(self):
        params = load_model_config("segmentation", "kpconv")["PDSimpleKPConv"]
        model_class = getattr(params, "class")
        model_config = OmegaConf.merge(params, self.data_config)
        dataset = MockDatasetGeometric(5)
        model = _find_model_using_name(model_class, "segmentation", model_config, dataset)
        model.set_input(dataset[0])
        model.forward()
        model.backward()

    def test_kpconvpretransform(self):
        params = load_model_config("segmentation", "kpconv")["PDSimpleKPConv"]
        model_config = OmegaConf.merge(params, self.data_config)
        dataset = MockDatasetGeometric(5)
        model_class = getattr(params, "class")
        model = _find_model_using_name(model_class, "segmentation", model_config, dataset)
        model.eval()
        dataset_transform = MockDatasetGeometric(5)
        dataset_transform.set_strategies(model)
        model.set_input(dataset[0])
        model.forward()
        model.get_output()

        torch.testing.assert_allclose(dataset_transform[0].pos, dataset[0].pos)
        # model.set_input(dataset_transform[0])
        # model.forward()
        # output_tr = model.get_output()
        # torch.testing.assert_allclose(output, output_tr)
        # model.backward()

    def test_largekpconv(self):
        params = load_model_config("segmentation", "kpconv")["KPConvPaper"]
        model_class = getattr(params, "class")
        model_config = OmegaConf.merge(params, self.data_config)
        dataset = MockDatasetGeometric(5)
        model = _find_model_using_name(model_class, "segmentation", model_config, dataset)
        model.set_input(dataset[0])
        model.forward()
        model.backward()

    def test_pointnet2ms(self):
        params = load_model_config("segmentation", "pointnet2")["pointnet2ms"]
        model_class = getattr(params, "class")
        model_config = OmegaConf.merge(params, self.data_config)
        dataset = MockDatasetGeometric(5)
        model = _find_model_using_name(model_class, "segmentation", model_config, dataset)
        model.set_input(dataset[0])
        model.forward()
        model.backward()

    # def test_pointnet2_customekernel(self):
    #     model_type = 'pointnet2_dense'
    #     params = self.config['models']['pointnet2_kc']
    #     dataset = MockDataset(5)
    #     model = _find_model_using_name(model_type, 'segmentation', params, dataset)
    #     model.set_input(dataset[0])
    #     model.forward()


if __name__ == "__main__":
    unittest.main()
