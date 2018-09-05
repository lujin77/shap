from __future__ import print_function
from .. import datasets
from . import metrics
from . import models
from . import methods
from .. import __version__
import numpy as np
import sklearn
import os
import pickle
import sys
import time
import subprocess
from multiprocessing import Pool
import itertools
import copy
import random
import time
try:
    from queue import Queue
except ImportError:
    from Queue import Queue
from threading import Thread, Lock


regression_metrics = [
    "runtime",
    "local_accuracy",
    "consistency_guarantees",
    "mask_keep_positive",
    "mask_keep_negative",
    "keep_positive",
    "keep_negative",
    "batch_keep_absolute__r2",
    "mask_remove_positive",
    "mask_remove_negative",
    "remove_positive",
    "remove_negative",
    "batch_remove_absolute__r2"
]

binary_classification_metrics = [
    "runtime",
    "local_accuracy",
    "consistency_guarantees",
    "mask_keep_positive",
    "mask_keep_negative",
    "keep_positive",
    "keep_negative",
    "batch_keep_absolute__roc_auc",
    "mask_remove_positive",
    "mask_remove_negative",
    "remove_positive",
    "remove_negative",
    "batch_remove_absolute__roc_auc"
]

linear_regress_methods = [
    "linear_shap_corr",
    "linear_shap_ind",
    "coef",
    "random",
    "kernel_shap_1000_meanref",
    #"kernel_shap_100_meanref",
    #"sampling_shap_10000",
    "sampling_shap_1000",
    #"lime_tabular_regression_1000"
    #"sampling_shap_100"
]

linear_classify_methods = [
    # NEED LIME
    "linear_shap_corr",
    "linear_shap_ind",
    "coef",
    "random",
    "kernel_shap_1000_meanref",
    #"kernel_shap_100_meanref",
    #"sampling_shap_10000",
    "sampling_shap_1000",
    #"lime_tabular_regression_1000"
    #"sampling_shap_100"
]

tree_regress_methods = [
    # NEED tree_shap_ind
    # NEED split_count?
    "tree_shap",
    "saabas",
    "random",
    "tree_gain",
    "kernel_shap_1000_meanref",
    "mean_abs_tree_shap",
    #"kernel_shap_100_meanref",
    #"sampling_shap_10000",
    "sampling_shap_1000",
    #"lime_tabular_regression_1000"
    #"sampling_shap_100"
]

tree_classify_methods = [
    # NEED tree_shap_ind
    # NEED split_count?
    "tree_shap",
    "saabas",
    "random",
    "tree_gain",
    "kernel_shap_1000_meanref",
    "mean_abs_tree_shap",
    #"kernel_shap_100_meanref",
    #"sampling_shap_10000",
    "sampling_shap_1000",
    #"lime_tabular_regression_1000"
    #"sampling_shap_100"
]

deep_regress_methods = [
    "deep_shap",
    "expected_gradients",
    "random",
    "kernel_shap_1000_meanref",
    "sampling_shap_1000",
    #"lime_tabular_regression_1000"
]

_experiments = []
_experiments += [["corrgroups60", "lasso", m, s] for s in regression_metrics for m in linear_regress_methods]
_experiments += [["corrgroups60", "ridge", m, s] for s in regression_metrics for m in linear_regress_methods]
_experiments += [["corrgroups60", "decision_tree", m, s] for s in regression_metrics for m in tree_regress_methods]
_experiments += [["corrgroups60", "random_forest", m, s] for s in regression_metrics for m in tree_regress_methods]
_experiments += [["corrgroups60", "gbm", m, s] for s in regression_metrics for m in tree_regress_methods]
_experiments += [["corrgroups60", "ffnn", m, s] for s in regression_metrics for m in deep_regress_methods]

_experiments += [["cric", "lasso", m, s] for s in binary_classification_metrics for m in linear_classify_methods]
_experiments += [["cric", "ridge", m, s] for s in binary_classification_metrics for m in linear_classify_methods]
_experiments += [["cric", "decision_tree", m, s] for s in binary_classification_metrics for m in tree_regress_methods]
_experiments += [["cric", "random_forest", m, s] for s in binary_classification_metrics for m in tree_regress_methods]
_experiments += [["cric", "gbm", m, s] for s in binary_classification_metrics for m in tree_regress_methods]
#_experiments += [["cric", "ffnn", m, s] for s in binary_classification_metrics for m in deep_regress_methods]

def experiments(dataset=None, model=None, method=None, metric=None):
    for experiment in _experiments:
        if dataset is not None and dataset != experiment[0]:
            continue
        if model is not None and model != experiment[1]:
            continue
        if method is not None and method != experiment[2]:
            continue
        if metric is not None and metric != experiment[3]:
            continue
        yield experiment

def run_experiment(experiment, use_cache=True, cache_dir="/tmp"):
    dataset_name, model_name, method_name, metric_name = experiment

    # see if we have a cached version
    cache_id = __gen_cache_id(experiment)
    cache_file = os.path.join(cache_dir, cache_id + ".pickle")
    if use_cache and os.path.isfile(cache_file):
        with open(cache_file, "rb") as f:
            #print(cache_id.replace("__", " ") + " ...loaded from cache.")
            return pickle.load(f)

    # compute the scores
    print(cache_id.replace("__", " ") + " ...")
    sys.stdout.flush()
    start = time.time()
    X,y = getattr(datasets, dataset_name)()
    score = getattr(metrics, metric_name)(
        X, y,
        getattr(models, dataset_name+"__"+model_name),
        method_name
    )
    print("...took %f seconds.\n" % (time.time() - start))

    # cache the scores
    with open(cache_file, "wb") as f:
        pickle.dump(score, f)

    return score
        

def run_experiments_helper(args):
    experiment, cache_dir = args
    return run_experiment(experiment, cache_dir=cache_dir)

def run_experiments(dataset=None, model=None, method=None, metric=None, cache_dir="/tmp", nworkers=1):
    experiments_arr = list(experiments(dataset=dataset, model=model, method=method, metric=metric))
    if nworkers == 1:
        out = list(map(run_experiments_helper, zip(experiments_arr, itertools.repeat(cache_dir))))
    else:
        with Pool(nworkers) as pool:
            out = pool.map(run_experiments_helper, zip(experiments_arr, itertools.repeat(cache_dir)))
    return list(zip(experiments_arr, out))


nexperiments = 0 
total_sent = 0
total_done = 0
total_failed = 0
host_records = {}
worker_lock = Lock()
ssh_conn_per_min_limit = 5
def __thread_worker(q, host):
    global total_sent, total_done
    hostname, python_binary = host.split(":")
    while True:
        experiment = q.get()

        # make sure we are not sending too many ssh connections to the host
        while True:
            all_clear = False

            worker_lock.acquire()
            try:
                if hostname not in host_records:
                    host_records[hostname] = []
                
                if len(host_records[hostname]) < ssh_conn_per_min_limit:
                    all_clear = True
                elif time.time() - host_records[hostname][-ssh_conn_per_min_limit] > 60:
                    all_clear = True
            finally:
                worker_lock.release()
            
            # if we are clear to send a new ssh connection then break
            if all_clear:
                break

            # if we are not clear then we sleep and try again
            time.sleep(5)

        # record how many we have sent off for executation
        worker_lock.acquire()
        try:
            total_sent += 1
            __print_status()
        finally:
            worker_lock.release()
        
        __run_remote_experiment(experiment, hostname, python_binary=python_binary)
        
        # record how many are finished
        worker_lock.acquire()
        try:
            total_done += 1
            __print_status()
        finally:
            worker_lock.release()
        
        q.task_done()

def __print_status():
    print("Benchmark task %d of %d done (%d failed, %d running)" % (total_done, nexperiments, total_failed, total_sent - total_done), end="\r")
    sys.stdout.flush()


def run_remote_experiments(experiments, thread_hosts, rate_limits={}):
    """ Use ssh to run the experiments on remote machines in parallel.

    Parameters
    ----------
    experiments : iterable
        Output of shap.benchmark.experiments(...).

    thread_hosts : list of strings
        Each host has the format "host_name:path_to_python_binary" and can appear multiple times
        in the list (one for each parallel execution you want on that machine).
    """
    
    # first we kill any remaining workers from previous runs
    # note we don't check_call because pkill kills our ssh call as well
    thread_hosts = copy.copy(thread_hosts)
    random.shuffle(thread_hosts)
    for host in set(thread_hosts):
        hostname,_ = host.split(":")
        try:
            subprocess.run(["ssh", hostname, "pkill -f shap.benchmark.run_experiment"], timeout=15)
        except subprocess.TimeoutExpired:
            print("Failed to connect to", hostname, "after 15 seconds! Exiting.")
            return
    
    global nexperiments
    experiments = copy.copy(list(experiments))
    random.shuffle(experiments) # this way all the hard experiments don't get put on one machine
    nexperiments = len(experiments)

    q = Queue()

    for host in thread_hosts:
        worker = Thread(target=__thread_worker, args=(q, host))
        worker.setDaemon(True)
        worker.start()

    for experiment in experiments:
        q.put(experiment)

    q.join()

def __run_remote_experiment(experiment, remote, cache_dir="/tmp", python_binary="python"):
    global total_failed
    dataset_name, model_name, method_name, metric_name = experiment

    # see if we have a cached version
    cache_id = __gen_cache_id(experiment)
    cache_file = os.path.join(cache_dir, cache_id + ".pickle")
    if os.path.isfile(cache_file):
        with open(cache_file, "rb") as f:
            return pickle.load(f)
    
    # this is just so we don't dump everything at once on a machine
    time.sleep(random.uniform(0,5))

    # run the benchmark on the remote machine
    #start = time.time()
    cmd = "CUDA_VISIBLE_DEVICES=\"\" "+python_binary+" -c \"import shap; shap.benchmark.run_experiment(['%s', '%s', '%s', '%s'], cache_dir='%s')\" &> %s/%s.output" % (
        dataset_name, model_name, method_name, metric_name, cache_dir, cache_dir, cache_id
    )
    try:
        subprocess.check_output(["ssh", remote, cmd])
    except subprocess.CalledProcessError as e:
        print("The following command failed on %s:" % remote, file=sys.stderr)
        print(cmd, file=sys.stderr)
        total_failed += 1
        print(e)
        return

    # copy the results back
    subprocess.check_output(["scp", remote+":"+cache_file, cache_file])

    if os.path.isfile(cache_file):
        with open(cache_file, "rb") as f:
            #print(cache_id.replace("__", " ") + " ...loaded from remote after %f seconds" % (time.time() - start))
            return pickle.load(f)
    else:
        raise Exception("Remote benchmark call finished but no local file was found!")

def __gen_cache_id(experiment):
    dataset_name, model_name, method_name, metric_name = experiment
    return "v" + "__".join([__version__, dataset_name, model_name, method_name, metric_name])