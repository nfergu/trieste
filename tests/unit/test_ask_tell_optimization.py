# Copyright 2021 The Trieste Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations

from typing import Mapping, Optional

import numpy.testing as npt
import pytest
import tensorflow as tf

from tests.util.misc import FixedAcquisitionRule, assert_datasets_allclose, mk_dataset
from tests.util.models.gpflow.models import (
    GaussianProcess,
    PseudoTrainableProbModel,
    QuadraticMeanAndRBFKernel,
    rbf,
)
from trieste.acquisition.rule import AcquisitionRule, LocalDatasetsAcquisitionRule
from trieste.acquisition.utils import copy_to_local_models
from trieste.ask_tell_optimization import AskTellOptimizer
from trieste.bayesian_optimizer import OptimizationResult, Record
from trieste.data import Dataset
from trieste.models.interfaces import ProbabilisticModel, TrainableProbabilisticModel
from trieste.objectives.utils import mk_batch_observer
from trieste.observer import OBJECTIVE
from trieste.space import Box, SearchSpace
from trieste.types import State, Tag, TensorType
from trieste.utils.misc import LocalizedTag

# tags
TAG1: Tag = "1"
TAG2: Tag = "2"


class LinearWithUnitVariance(GaussianProcess, PseudoTrainableProbModel):
    def __init__(self) -> None:
        super().__init__([lambda x: 2 * x], [rbf()])
        self._optimize_count = 0

    def optimize(self, dataset: Dataset) -> None:
        self._optimize_count += 1

    @property
    def optimize_count(self) -> int:
        return self._optimize_count


@pytest.fixture
def search_space() -> Box:
    return Box([-1], [1])


@pytest.fixture
def init_dataset() -> Dataset:
    return mk_dataset([[0.0]], [[0.0]])


@pytest.fixture
def acquisition_rule() -> AcquisitionRule[TensorType, Box, ProbabilisticModel]:
    return FixedAcquisitionRule([[0.0]])


@pytest.fixture
def model() -> TrainableProbabilisticModel:
    return LinearWithUnitVariance()


def test_ask_tell_optimizer_suggests_new_point(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
) -> None:
    ask_tell = AskTellOptimizer(search_space, init_dataset, model, acquisition_rule)

    new_point = ask_tell.ask()

    assert len(new_point) == 1


def test_ask_tell_optimizer_with_default_acquisition_suggests_new_point(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
) -> None:
    ask_tell = AskTellOptimizer(search_space, init_dataset, model)

    new_point = ask_tell.ask()

    assert len(new_point) == 1


@pytest.mark.parametrize("copy", [True, False])
def test_ask_tell_optimizer_returns_complete_state(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
    copy: bool,
) -> None:
    ask_tell = AskTellOptimizer(search_space, init_dataset, model, acquisition_rule)

    state_record: Record[None] = ask_tell.to_record(copy=copy)

    assert_datasets_allclose(state_record.dataset, init_dataset)
    assert isinstance(state_record.model, type(model))
    assert state_record.acquisition_state is None


@pytest.mark.parametrize("copy", [True, False])
def test_ask_tell_optimizer_loads_from_state(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
    copy: bool,
) -> None:
    old_state: Record[None] = Record({OBJECTIVE: init_dataset}, {OBJECTIVE: model}, None)

    ask_tell = AskTellOptimizer.from_record(old_state, search_space, acquisition_rule)
    new_state: Record[None] = ask_tell.to_record(copy=copy)

    assert_datasets_allclose(old_state.dataset, new_state.dataset)
    assert isinstance(new_state.model, type(old_state.model))


@pytest.mark.parametrize("copy", [True, False])
def test_ask_tell_optimizer_returns_optimization_result(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
    copy: bool,
) -> None:
    ask_tell = AskTellOptimizer(search_space, init_dataset, model, acquisition_rule)

    result: OptimizationResult[None] = ask_tell.to_result(copy=copy)

    assert_datasets_allclose(result.try_get_final_dataset(), init_dataset)
    assert isinstance(result.try_get_final_model(), type(model))


def test_ask_tell_optimizer_updates_state_with_new_data(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
) -> None:
    new_data = mk_dataset([[1.0]], [[1.0]])
    ask_tell = AskTellOptimizer(search_space, init_dataset, model, acquisition_rule)

    ask_tell.tell(new_data)
    state_record: Record[None] = ask_tell.to_record()

    assert_datasets_allclose(state_record.dataset, init_dataset + new_data)


@pytest.mark.parametrize("copy", [True, False])
def test_ask_tell_optimizer_copies_state(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
    copy: bool,
) -> None:
    new_data = mk_dataset([[1.0]], [[1.0]])
    ask_tell = AskTellOptimizer(search_space, init_dataset, model, acquisition_rule)
    state_start: Record[None] = ask_tell.to_record(copy=copy)
    ask_tell.tell(new_data)
    state_end: Record[None] = ask_tell.to_record(copy=copy)

    assert_datasets_allclose(state_start.dataset, init_dataset if copy else init_dataset + new_data)
    assert_datasets_allclose(state_end.dataset, init_dataset + new_data)
    assert state_start.model is not model if copy else state_start.model is model


def test_ask_tell_optimizer_datasets_property(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
) -> None:
    ask_tell = AskTellOptimizer(search_space, init_dataset, model, acquisition_rule)
    assert_datasets_allclose(ask_tell.datasets[OBJECTIVE], init_dataset)
    assert_datasets_allclose(ask_tell.dataset, init_dataset)


def test_ask_tell_optimizer_models_property(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
) -> None:
    ask_tell = AskTellOptimizer(search_space, init_dataset, model, acquisition_rule)
    assert ask_tell.models[OBJECTIVE] is model
    assert ask_tell.model is model


def test_ask_tell_optimizer_models_setter(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
) -> None:
    ask_tell = AskTellOptimizer(search_space, init_dataset, model, acquisition_rule)
    model2 = LinearWithUnitVariance()
    ask_tell.models = {OBJECTIVE: model2}
    assert ask_tell.models[OBJECTIVE] is model2 is not model


def test_ask_tell_optimizer_models_setter_errors(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
) -> None:
    ask_tell = AskTellOptimizer(search_space, init_dataset, model, acquisition_rule)
    with pytest.raises(ValueError):
        ask_tell.models = {}
    with pytest.raises(ValueError):
        ask_tell.models = {OBJECTIVE: LinearWithUnitVariance(), "X": LinearWithUnitVariance()}
    with pytest.raises(ValueError):
        ask_tell.models = {"CONSTRAINT": LinearWithUnitVariance()}


def test_ask_tell_optimizer_model_setter(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
) -> None:
    ask_tell = AskTellOptimizer(search_space, init_dataset, model, acquisition_rule)
    model2 = LinearWithUnitVariance()
    ask_tell.model = model2
    assert ask_tell.models[OBJECTIVE] is model2 is not model


def test_ask_tell_optimizer_model_setter_errors(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
) -> None:
    one_model = AskTellOptimizer(search_space, {"X": init_dataset}, {"X": model}, acquisition_rule)
    with pytest.raises(ValueError):
        one_model.model = model
    two_models = AskTellOptimizer(
        search_space,
        {OBJECTIVE: init_dataset, "X": init_dataset},
        {OBJECTIVE: model, "X": model},
        acquisition_rule,
    )
    with pytest.raises(ValueError):
        two_models.model = model


def test_ask_tell_optimizer_trains_model(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
) -> None:
    new_data = mk_dataset([[1.0]], [[1.0]])
    ask_tell = AskTellOptimizer(
        search_space, init_dataset, model, acquisition_rule, fit_model=False
    )

    ask_tell.tell(new_data)
    state_record: Record[None] = ask_tell.to_record()

    assert state_record.model.optimize_count == 1  # type: ignore


@pytest.mark.parametrize("fit_initial_model", [True, False])
def test_ask_tell_optimizer_optimizes_initial_model(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
    fit_initial_model: bool,
) -> None:
    ask_tell = AskTellOptimizer(
        search_space, init_dataset, model, acquisition_rule, fit_model=fit_initial_model
    )
    state_record: Record[None] = ask_tell.to_record()

    if fit_initial_model:
        assert state_record.model.optimize_count == 1  # type: ignore
    else:
        assert state_record.model.optimize_count == 0  # type: ignore


def test_ask_tell_optimizer_from_state_does_not_train_model(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
) -> None:
    old_state: Record[None] = Record({OBJECTIVE: init_dataset}, {OBJECTIVE: model}, None)

    ask_tell = AskTellOptimizer.from_record(old_state, search_space, acquisition_rule)
    state_record: Record[None] = ask_tell.to_record()

    assert state_record.model.optimize_count == 0  # type: ignore


@pytest.mark.parametrize(
    "starting_state, expected_state",
    [(None, 1), (0, 1), (3, 4)],
)
def test_ask_tell_optimizer_uses_specified_acquisition_state(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    starting_state: int | None,
    expected_state: int,
) -> None:
    class Rule(AcquisitionRule[State[Optional[int], TensorType], Box, ProbabilisticModel]):
        def __init__(self) -> None:
            self.states_received: list[int | None] = []

        def acquire(
            self,
            search_space: Box,
            models: Mapping[Tag, ProbabilisticModel],
            datasets: Optional[Mapping[Tag, Dataset]] = None,
        ) -> State[int | None, TensorType]:
            def go(state: int | None) -> tuple[int | None, TensorType]:
                self.states_received.append(state)

                if state is None:
                    state = 0

                return state + 1, tf.constant([[0.0]], tf.float64)

            return go

    rule = Rule()

    ask_tell = AskTellOptimizer(
        search_space, init_dataset, model, rule, acquisition_state=starting_state
    )
    _ = ask_tell.ask()
    state_record: Record[State[int, TensorType]] = ask_tell.to_record()

    # mypy cannot see that this is in fact int
    assert state_record.acquisition_state == expected_state  # type: ignore
    assert ask_tell.acquisition_state == expected_state


def test_ask_tell_optimizer_does_not_accept_empty_datasets_or_models(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
) -> None:
    with pytest.raises(ValueError):
        AskTellOptimizer(search_space, {}, model, acquisition_rule)  # type: ignore

    with pytest.raises(ValueError):
        AskTellOptimizer(search_space, init_dataset, {}, acquisition_rule)  # type: ignore


def test_ask_tell_optimizer_validates_keys(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
) -> None:
    dataset_with_key_1 = {TAG1: init_dataset}
    model_with_key_2 = {TAG2: model}

    with pytest.raises(ValueError):
        AskTellOptimizer(search_space, dataset_with_key_1, model_with_key_2, acquisition_rule)


def test_ask_tell_optimizer_tell_validates_keys(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
) -> None:
    dataset_with_key_1 = {TAG1: init_dataset}
    model_with_key_1 = {TAG1: model}
    new_data_with_key_2 = {TAG2: mk_dataset([[1.0]], [[1.0]])}

    ask_tell = AskTellOptimizer(
        search_space, dataset_with_key_1, model_with_key_1, acquisition_rule
    )
    with pytest.raises(KeyError, match=str(TAG2)):
        ask_tell.tell(new_data_with_key_2)


def test_ask_tell_optimizer_default_acquisition_requires_objective_tag(
    search_space: Box,
    init_dataset: Dataset,
    model: TrainableProbabilisticModel,
) -> None:
    wrong_tag: Tag = f"{OBJECTIVE}_WRONG"
    wrong_datasets = {wrong_tag: init_dataset}
    wrong_models = {wrong_tag: model}

    with pytest.raises(ValueError):
        AskTellOptimizer(search_space, wrong_datasets, wrong_models)


def test_ask_tell_optimizer_for_uncopyable_model(
    search_space: Box,
    init_dataset: Dataset,
    acquisition_rule: AcquisitionRule[TensorType, Box, TrainableProbabilisticModel],
) -> None:
    class _UncopyableModel(LinearWithUnitVariance):
        def __deepcopy__(self, memo: dict[int, object]) -> _UncopyableModel:
            raise MemoryError

    model = _UncopyableModel()
    ask_tell = AskTellOptimizer(search_space, init_dataset, model, acquisition_rule)

    with pytest.raises(NotImplementedError):
        ask_tell.to_result()
    assert ask_tell.to_result(copy=False).final_result.is_ok

    ask_tell.tell(mk_dataset([[1.0]], [[1.0]]))

    with pytest.raises(NotImplementedError):
        ask_tell.to_result()
    assert ask_tell.to_result(copy=False).final_result.is_ok


class DatasetChecker(QuadraticMeanAndRBFKernel, PseudoTrainableProbModel):
    def __init__(
        self,
        use_global_model: bool,
        use_global_init_dataset: bool,
        init_data: Mapping[Tag, Dataset],
        query_points: TensorType,
    ) -> None:
        super().__init__()
        self.update_count = 0
        self._tag = OBJECTIVE
        self.use_global_model = use_global_model
        self.use_global_init_dataset = use_global_init_dataset
        self.init_data = init_data
        self.query_points = query_points

    def update(self, dataset: Dataset) -> None:
        if self.use_global_model:
            exp_init_qps = self.init_data[OBJECTIVE].query_points
        else:
            if self.use_global_init_dataset:
                exp_init_qps = self.init_data[OBJECTIVE].query_points
            else:
                exp_init_qps = self.init_data[self._tag].query_points

        if self.update_count == 0:
            # Initial model training.
            exp_qps = exp_init_qps
        else:
            # Subsequent model training.
            if self.use_global_model:
                exp_qps = tf.concat([exp_init_qps, tf.reshape(self.query_points, [-1, 1])], 0)
            else:
                index = LocalizedTag.from_tag(self._tag).local_index
                exp_qps = tf.concat([exp_init_qps, self.query_points[:, index]], 0)

        npt.assert_array_equal(exp_qps, dataset.query_points)
        self.update_count += 1


class LocalDatasetsFixedAcquisitionRule(
    FixedAcquisitionRule,
    LocalDatasetsAcquisitionRule[TensorType, SearchSpace, ProbabilisticModel],
):
    def __init__(self, query_points: TensorType, num_local_datasets: int) -> None:
        super().__init__(query_points)
        self._num_local_datasets = num_local_datasets

    @property
    def num_local_datasets(self) -> int:
        return self._num_local_datasets


# Check that the correct dataset is routed to the model.
# Note: this test is almost identical to the one in test_bayesian_optimizer.py.
@pytest.mark.parametrize("use_global_model", [True, False])
@pytest.mark.parametrize("use_global_init_dataset", [True, False])
@pytest.mark.parametrize("num_query_points_per_batch", [1, 2])
def test_ask_tell_optimizer_creates_correct_datasets_for_rank3_points(
    use_global_model: bool, use_global_init_dataset: bool, num_query_points_per_batch: int
) -> None:
    batch_size = 4
    if use_global_init_dataset:
        init_data = {OBJECTIVE: mk_dataset([[0.5], [1.5]], [[0.25], [0.35]])}
    else:
        init_data = {
            LocalizedTag(OBJECTIVE, i): mk_dataset([[0.5 + i], [1.5 + i]], [[0.25], [0.35]])
            for i in range(batch_size)
        }
        init_data[OBJECTIVE] = mk_dataset([[0.5], [1.5]], [[0.25], [0.35]])

    query_points = tf.reshape(
        tf.constant(range(batch_size * num_query_points_per_batch), tf.float64),
        (num_query_points_per_batch, batch_size, 1),
    )

    search_space = Box([-1], [1])

    model = DatasetChecker(use_global_model, use_global_init_dataset, init_data, query_points)
    if use_global_model:
        models = {OBJECTIVE: model}
    else:
        models = copy_to_local_models(model, batch_size)  # type: ignore[assignment]
    for tag, model in models.items():
        model._tag = tag

    observer = mk_batch_observer(lambda x: Dataset(x, x))
    rule = LocalDatasetsFixedAcquisitionRule(query_points, batch_size)
    ask_tell = AskTellOptimizer(search_space, init_data, models, rule)

    points = ask_tell.ask()
    new_data = observer(points)
    ask_tell.tell(new_data)
