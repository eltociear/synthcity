# stdlib
from pathlib import Path
from typing import Any, List, Optional

# third party
import pandas as pd
from pydantic import validate_arguments

# synthcity absolute
from synthcity.metrics.weighted_metrics import WeightedMetrics
from synthcity.plugins.core.dataloader import DataLoader
from synthcity.plugins.core.distribution import (
    CategoricalDistribution,
    Distribution,
    FloatDistribution,
    IntegerDistribution,
)
from synthcity.plugins.core.models.flows import NormalizingFlows
from synthcity.plugins.core.models.tabular_flows import TabularFlows
from synthcity.plugins.core.plugin import Plugin
from synthcity.plugins.core.schema import Schema
from synthcity.utils.constants import DEVICE


class NormalizingFlowsPlugin(Plugin):
    """
    .. inheritance-diagram:: synthcity.plugins.generic.plugin_nflow.NormalizingFlowsPlugin
        :parts: 1

    Normalizing Flows methods.

    Normalizing Flows are generative models which produce tractable distributions where both sampling and density evaluation can be efficient and exact.

    Args:
        n_iter: int
            Number of flow steps
        n_layers_hidden: int
            Number of transformation layers
        n_units_hidden: int
            Number of hidden units for each layer
        batch_size: int
            Size of batch used for training
        num_transform_blocks: int
            Number of blocks to use in coupling/autoregressive nets.
        dropout: float
            Dropout probability for coupling/autoregressive nets.
        batch_norm: bool
            Whether to use batch norm in coupling/autoregressive nets.
        num_bins: int
            Number of bins to use for piecewise transforms.
        tail_bound: float
            Box is on [-bound, bound]^2
        lr: float
            Learning rate for optimizer.
        apply_unconditional_transform: bool
            Whether to unconditionally transform \'identity\' features in the coupling layer.
        base_distribution: str
            Possible values: "standard_normal"
        linear_transform_type: str
            Type of linear transform to use. Possible values:
                - lu : A linear transform where we parameterize the LU decomposition of the weights.
                - permutation: Permutes using a random, but fixed, permutation.
                - svd: A linear module using the SVD decomposition for the weight matrix.
        base_transform_type: str
            Type of transform to use between linear layers. Possible values:
                - affine-coupling : An affine coupling layer that scales and shifts part of the variables.
                    Ref: L. Dinh et al., "Density estimation using Real NVP".
                - quadratic-coupling :
                    Ref: Müller et al., "Neural Importance Sampling".
                - rq-coupling : Rational Quadratic Coupling
                    Ref: Durkan et al, "Neural Spline Flows".
                - affine-autoregressive :Affine Autoregressive Transform
                    Ref: Durkan et al, "Neural Spline Flows".
                - quadratic-autoregressive : Quadratic Autoregressive Transform
                    Ref: Durkan et al, "Neural Spline Flows".
                - rq-autoregressive : Rational Quadratic Autoregressive Transform
                    Ref: Durkan et al, "Neural Spline Flows".
        # early stopping
        n_iter_print: int
            Number of iterations after which to print updates and check the validation loss.
        n_iter_min: int
            Minimum number of iterations to go through before starting early stopping
        patience: int
            Max number of iterations without any improvement before training early stopping is trigged.
        patience_metric: Optional[WeightedMetrics]
            If not None, the metric is used for evaluation the criterion for training early stopping.
        # Core Plugin arguments
        workspace: Path.
            Optional Path for caching intermediary results.
        compress_dataset: bool. Default = False.
            Drop redundant features before training the generator.
        sampling_patience: int.
            Max inference iterations to wait for the generated data to match the training schema.
        random_state: int
            random seed to use
    Example:
        >>> from sklearn.datasets import load_iris
        >>> from synthcity.plugins import Plugins
        >>>
        >>> X, y = load_iris(as_frame = True, return_X_y = True)
        >>> X["target"] = y
        >>>
        >>> plugin = Plugins().get("nflow", n_iter = 100)
        >>> plugin.fit(X)
        >>>
        >>> plugin.generate(50)

    """

    @validate_arguments(config=dict(arbitrary_types_allowed=True))
    def __init__(
        self,
        n_iter: int = 1000,
        n_layers_hidden: int = 1,
        n_units_hidden: int = 100,
        batch_size: int = 500,
        num_transform_blocks: int = 1,
        dropout: float = 0.1,
        batch_norm: bool = False,
        num_bins: int = 8,
        tail_bound: float = 3,
        lr: float = 1e-3,
        apply_unconditional_transform: bool = True,
        base_distribution: str = "standard_normal",  # "standard_normal"
        linear_transform_type: str = "permutation",  # "lu", "permutation", "svd"
        base_transform_type: str = "rq-autoregressive",  # "affine-coupling", "quadratic-coupling", "rq-coupling", "affine-autoregressive", "quadratic-autoregressive", "rq-autoregressive"
        encoder_max_clusters: int = 10,
        tabular: bool = True,
        # early stopping
        n_iter_min: int = 100,
        n_iter_print: int = 50,
        patience: int = 5,
        patience_metric: Optional[WeightedMetrics] = None,
        # core plugin arguments
        workspace: Path = Path("workspace"),
        compress_dataset: bool = False,
        sampling_patience: int = 500,
        random_state: int = 0,
        device: Any = DEVICE,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            device=device,
            random_state=random_state,
            sampling_patience=sampling_patience,
            workspace=workspace,
            compress_dataset=compress_dataset,
            **kwargs,
        )

        if patience_metric is None:
            patience_metric = WeightedMetrics(
                metrics=[("detection", "detection_mlp")],
                weights=[1],
                workspace=workspace,
            )

        self.n_iter = n_iter
        self.n_layers_hidden = n_layers_hidden
        self.n_units_hidden = n_units_hidden
        self.batch_size = batch_size
        self.num_transform_blocks = num_transform_blocks
        self.dropout = dropout
        self.batch_norm = batch_norm
        self.num_bins = num_bins
        self.tail_bound = tail_bound
        self.apply_unconditional_transform = apply_unconditional_transform
        self.lr = lr

        self.base_distribution = base_distribution
        self.linear_transform_type = linear_transform_type
        self.base_transform_type = base_transform_type

        self.encoder_max_clusters = encoder_max_clusters
        self.tabular = tabular

        self.n_iter_min = n_iter_min
        self.n_iter_print = n_iter_print
        self.patience = patience
        self.patience_metric = patience_metric

    @staticmethod
    def name() -> str:
        return "nflow"

    @staticmethod
    def type() -> str:
        return "generic"

    @staticmethod
    def hyperparameter_space(**kwargs: Any) -> List[Distribution]:
        return [
            IntegerDistribution(name="n_iter", low=100, high=5000, step=100),
            IntegerDistribution(name="n_layers_hidden", low=1, high=10),
            IntegerDistribution(name="n_units_hidden", low=10, high=100),
            CategoricalDistribution(name="batch_size", choices=[32, 64, 128, 256, 512]),
            FloatDistribution(name="dropout", low=0, high=0.2),
            CategoricalDistribution(name="batch_norm", choices=[True, False]),
            CategoricalDistribution(name="lr", choices=[1e-3, 1e-4, 2e-4]),
            CategoricalDistribution(
                name="linear_transform_type", choices=["lu", "permutation", "svd"]
            ),
            CategoricalDistribution(
                name="base_transform_type",
                choices=[
                    "affine-coupling",
                    "quadratic-coupling",
                    "rq-coupling",
                    "affine-autoregressive",
                    "quadratic-autoregressive",
                    "rq-autoregressive",
                ],
            ),
        ]

    def _fit(
        self, X: DataLoader, *args: Any, **kwargs: Any
    ) -> "NormalizingFlowsPlugin":
        if self.tabular:
            self.model = TabularFlows(
                X.dataframe(),
                n_iter=self.n_iter,
                n_layers_hidden=self.n_layers_hidden,
                n_units_hidden=self.n_units_hidden,
                batch_size=self.batch_size,
                num_transform_blocks=self.num_transform_blocks,
                dropout=self.dropout,
                batch_norm=self.batch_norm,
                num_bins=self.num_bins,
                tail_bound=self.tail_bound,
                lr=self.lr,
                apply_unconditional_transform=self.apply_unconditional_transform,
                base_distribution=self.base_distribution,
                linear_transform_type=self.linear_transform_type,
                base_transform_type=self.base_transform_type,
                encoder_max_clusters=self.encoder_max_clusters,
                n_iter_min=self.n_iter_min,
                n_iter_print=self.n_iter_print,
                patience=self.patience,
                patience_metric=self.patience_metric,
                device=self.device,
            )
        else:
            self.model = NormalizingFlows(
                n_iter=self.n_iter,
                n_layers_hidden=self.n_layers_hidden,
                n_units_hidden=self.n_units_hidden,
                batch_size=self.batch_size,
                num_transform_blocks=self.num_transform_blocks,
                dropout=self.dropout,
                batch_norm=self.batch_norm,
                num_bins=self.num_bins,
                tail_bound=self.tail_bound,
                lr=self.lr,
                apply_unconditional_transform=self.apply_unconditional_transform,
                base_distribution=self.base_distribution,
                linear_transform_type=self.linear_transform_type,
                base_transform_type=self.base_transform_type,
                n_iter_min=self.n_iter_min,
                n_iter_print=self.n_iter_print,
                patience=self.patience,
                patience_metric=self.patience_metric,
                device=self.device,
            )

        self.model.fit(X.dataframe())
        return self

    def _generate(self, count: int, syn_schema: Schema, **kwargs: Any) -> pd.DataFrame:
        def _internal_generate(count: int) -> pd.DataFrame:
            batch = min(5000, count)

            result = self.model.generate(1)
            max_retries = count / batch + 1

            count -= 1
            retries = 0

            while count > 0 and retries < max_retries:
                batch = min(batch, count)
                try:
                    result = pd.concat(
                        [result, self.model.generate(batch)], ignore_index=True
                    )
                except BaseException:
                    pass

                count -= batch
                retries += 1

            return result

        return self._safe_generate(_internal_generate, count, syn_schema)


plugin = NormalizingFlowsPlugin
