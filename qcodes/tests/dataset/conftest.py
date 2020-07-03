import tempfile
import gc
import os
from contextlib import contextmanager
import shutil

import pytest
import numpy as np

import qcodes as qc
from qcodes.dataset.sqlite.database import initialise_database, connect
from qcodes.dataset.descriptions.param_spec import ParamSpecBase
from qcodes.dataset.descriptions.dependencies import InterDependencies_
from qcodes import new_experiment, new_data_set
from qcodes.dataset.measurements import Measurement
from qcodes.tests.instrument_mocks import ArraySetPointParam, Multi2DSetPointParam
from qcodes.instrument.parameter import Parameter

n_experiments = 0


@pytest.fixture(scope="function")
def empty_temp_db(tmp_path):
    global n_experiments
    n_experiments = 0
    # create a temp database for testing
    try:
        qc.config["core"]["db_location"] = \
            str(tmp_path / 'temp.db')
        if os.environ.get('QCODES_SQL_DEBUG'):
            qc.config["core"]["db_debug"] = True
        else:
            qc.config["core"]["db_debug"] = False
        initialise_database()
        yield
    finally:
        # there is a very real chance that the tests will leave open
        # connections to the database. These will have gone out of scope at
        # this stage but a gc collection may not have run. The gc
        # collection ensures that all connections belonging to now out of
        # scope objects will be closed
        gc.collect()


@pytest.fixture(scope='function')
def empty_temp_db_connection(tmp_path):
    """
    Yield connection to an empty temporary DB file.
    """
    path = str(tmp_path / 'source.db')
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()
        # there is a very real chance that the tests will leave open
        # connections to the database. These will have gone out of scope at
        # this stage but a gc collection may not have run. The gc
        # collection ensures that all connections belonging to now out of
        # scope objects will be closed
        gc.collect()


@pytest.fixture(scope='function')
def two_empty_temp_db_connections(tmp_path):
    """
    Yield connections to two empty files. Meant for use with the
    test_database_extract_runs
    """

    source_path = str(tmp_path / 'source.db')
    target_path = str(tmp_path / 'target.db')
    source_conn = connect(source_path)
    target_conn = connect(target_path)
    try:
        yield (source_conn, target_conn)
    finally:
        source_conn.close()
        target_conn.close()
        # there is a very real chance that the tests will leave open
        # connections to the database. These will have gone out of scope at
        # this stage but a gc collection may not have run. The gc
        # collection ensures that all connections belonging to now out of
        # scope objects will be closed
        gc.collect()


@pytest.fixture(scope='function')
def experiment(empty_temp_db):
    e = new_experiment("test-experiment", sample_name="test-sample")
    try:
        yield e
    finally:
        e.conn.close()


@pytest.fixture(scope='function')
def dataset(experiment):
    dataset = new_data_set("test-dataset")
    try:
        yield dataset
    finally:
        dataset.unsubscribe_all()
        dataset.conn.close()


@contextmanager
def temporarily_copied_DB(filepath: str, **kwargs):
    """
    Make a temporary copy of a db-file and delete it after use. Meant to be
    used together with the old version database fixtures, lest we change the
    fixtures on disk. Yields the connection object

    Args:
        filepath: path to the db-file

    Kwargs:
        kwargs to be passed to connect
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        dbname_new = os.path.join(tmpdir, 'temp.db')
        shutil.copy2(filepath, dbname_new)

        conn = connect(dbname_new, **kwargs)

        try:
            yield conn

        finally:
            conn.close()


@pytest.fixture
def scalar_dataset(dataset):
    n_params = 3
    n_rows = 10**3
    params_indep = [ParamSpecBase(f'param_{i}',
                                  'numeric',
                                  label=f'param_{i}',
                                  unit='V')
                    for i in range(n_params)]
    param_dep = ParamSpecBase(f'param_{n_params}',
                              'numeric',
                              label=f'param_{n_params}',
                              unit='Ohm')

    all_params = params_indep + [param_dep]

    idps = InterDependencies_(dependencies={param_dep: tuple(params_indep)})

    dataset.set_interdependencies(idps)
    dataset.mark_started()
    dataset.add_results([{p.name: np.int(n_rows*10*pn+i)
                          for pn, p in enumerate(all_params)}
                         for i in range(n_rows)])
    dataset.mark_completed()
    yield dataset


@pytest.fixture
def scalar_dataset_with_nulls(dataset):
    """
    A very simple dataset. A scalar is varied, and two parameters are measured
    one by one
    """
    sp = ParamSpecBase('setpoint', 'numeric')
    val1 = ParamSpecBase('first_value', 'numeric')
    val2 = ParamSpecBase('second_value', 'numeric')

    idps = InterDependencies_(dependencies={val1: (sp,), val2: (sp,)})
    dataset.set_interdependencies(idps)

    dataset.mark_started()

    dataset.add_results([{sp.name: 0, val1.name: 1},
                         {sp.name: 0, val2.name: 2}])
    dataset.mark_completed()
    yield dataset


@pytest.fixture(scope="function",
                params=["array", "numeric"])
def array_dataset(experiment, request):
    meas = Measurement()
    param = ArraySetPointParam()
    meas.register_parameter(param, paramtype=request.param)

    with meas.run() as datasaver:
        datasaver.add_result((param, param.get(),))
    try:
        yield datasaver.dataset
    finally:
        datasaver.dataset.conn.close()

@pytest.fixture(scope="function",
                params=["array", "numeric"])
def array_dataset_with_nulls(experiment, request):
    """
    A dataset where two arrays are measured, one as a function
    of two other (setpoint) arrays, the other as a function of just one
    of them
    """
    meas = Measurement()
    meas.register_custom_parameter('sp1', paramtype=request.param)
    meas.register_custom_parameter('sp2', paramtype=request.param)
    meas.register_custom_parameter('val1', paramtype=request.param,
                                   setpoints=('sp1', 'sp2'))
    meas.register_custom_parameter('val2', paramtype=request.param,
                                   setpoints=('sp1',))

    with meas.run() as datasaver:
        sp1_vals = np.arange(0, 5)
        sp2_vals = np.arange(5, 10)
        val1_vals = np.ones(5)
        val2_vals = np.zeros(5)
        datasaver.add_result(('sp1', sp1_vals),
                             ('sp2', sp2_vals),
                             ('val1', val1_vals))
        datasaver.add_result(('sp1', sp1_vals),
                             ('val2', val2_vals))
    try:
        yield datasaver.dataset
    finally:
        datasaver.dataset.conn.close()


@pytest.fixture(scope="function",
                params=["array", "numeric"])
def multi_dataset(experiment, request):
    meas = Measurement()
    param = Multi2DSetPointParam()

    meas.register_parameter(param, paramtype=request.param)

    with meas.run() as datasaver:
        datasaver.add_result((param, param.get(),))
    try:
        yield datasaver.dataset
    finally:
        datasaver.dataset.conn.close()


@pytest.fixture(scope="function")
def array_in_scalar_dataset(experiment):
    meas = Measurement()
    scalar_param = Parameter('scalarparam', set_cmd=None)
    param = ArraySetPointParam()
    meas.register_parameter(scalar_param)
    meas.register_parameter(param, setpoints=(scalar_param,),
                            paramtype='array')

    with meas.run() as datasaver:
        for i in range(1, 10):
            scalar_param.set(i)
            datasaver.add_result((scalar_param, scalar_param.get()),
                                 (param, param.get()))
    try:
        yield datasaver.dataset
    finally:
        datasaver.dataset.conn.close()


@pytest.fixture(scope="function")
def varlen_array_in_scalar_dataset(experiment):
    meas = Measurement()
    scalar_param = Parameter('scalarparam', set_cmd=None)
    param = ArraySetPointParam()
    meas.register_parameter(scalar_param)
    meas.register_parameter(param, setpoints=(scalar_param,),
                            paramtype='array')
    np.random.seed(0)
    with meas.run() as datasaver:
        for i in range(1, 10):
            scalar_param.set(i)
            param.setpoints = (np.arange(i),)
            datasaver.add_result((scalar_param, scalar_param.get()),
                                 (param, np.random.rand(i)))
    try:
        yield datasaver.dataset
    finally:
        datasaver.dataset.conn.close()


@pytest.fixture(scope="function")
def array_in_scalar_dataset_unrolled(experiment):
    """
    This fixture yields a dataset where an array-valued parameter is registered
    as a 'numeric' type and has an additional single-valued setpoint. We
    expect data to be saved as individual scalars, with the scalar setpoint
    repeated.
    """
    meas = Measurement()
    scalar_param = Parameter('scalarparam', set_cmd=None)
    param = ArraySetPointParam()
    meas.register_parameter(scalar_param)
    meas.register_parameter(param, setpoints=(scalar_param,),
                            paramtype='numeric')

    with meas.run() as datasaver:
        for i in range(1, 10):
            scalar_param.set(i)
            datasaver.add_result((scalar_param, scalar_param.get()),
                                 (param, param.get()))
    try:
        yield datasaver.dataset
    finally:
        datasaver.dataset.conn.close()


@pytest.fixture(scope="function",
                params=["array", "numeric"])
def array_in_str_dataset(experiment, request):
    meas = Measurement()
    scalar_param = Parameter('textparam', set_cmd=None)
    param = ArraySetPointParam()
    meas.register_parameter(scalar_param, paramtype='text')
    meas.register_parameter(param, setpoints=(scalar_param,),
                            paramtype=request.param)

    with meas.run() as datasaver:
        for i in ['A', 'B', 'C']:
            scalar_param.set(i)
            datasaver.add_result((scalar_param, scalar_param.get()),
                                 (param, param.get()))
    try:
        yield datasaver.dataset
    finally:
        datasaver.dataset.conn.close()


@pytest.fixture
def standalone_parameters_dataset(dataset):
    n_params = 3
    n_rows = 10**3
    params_indep = [ParamSpecBase(f'param_{i}',
                                  'numeric',
                                  label=f'param_{i}',
                                  unit='V')
                    for i in range(n_params)]

    param_dep = ParamSpecBase(f'param_{n_params}',
                              'numeric',
                              label=f'param_{n_params}',
                              unit='Ohm')

    params_all = params_indep + [param_dep]

    idps = InterDependencies_(
        dependencies={param_dep: tuple(params_indep[0:1])},
        standalones=tuple(params_indep[1:]))

    dataset.set_interdependencies(idps)

    dataset.mark_started()
    dataset.add_results([{p.name: np.int(n_rows*10*pn+i)
                          for pn, p in enumerate(params_all)}
                         for i in range(n_rows)])
    dataset.mark_completed()
    yield dataset
