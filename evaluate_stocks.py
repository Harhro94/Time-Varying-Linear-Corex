from __future__ import division
from __future__ import absolute_import
from __future__ import print_function

from generate_data import *
from misc_utils import make_sure_path_exists, make_buckets
from sklearn.model_selection import train_test_split
from theano_time_corex import *

import pickle
import argparse
import baselines
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--nt', type=int, help='number of buckets')
    parser.add_argument('--nv', type=int, help='number of variables')
    parser.add_argument('--train_cnt', default=16, type=int, help='number of train samples')
    parser.add_argument('--val_cnt', default=16, type=int, help='number of validation samples')
    parser.add_argument('--test_cnt', default=100, type=int, help='number of test samples')
    parser.add_argument('--prefix', type=str, default='', help='optional prefix of experiment name')
    parser.add_argument('--data_type', dest='data_type', action='store', default='syn_nglf_buckets',
                        choices=['stock_day', 'stock_week'],
                        help='which dataset to load/create')
    args = parser.parse_args()

    args.train_data, args.val_data, args.test_data = load_stock_data(
        nt=args.nt, nv=args.nv, train_cnt=args.train_cnt, val_cnt=args.val_cnt, test_cnt=args.test_cnt,
        data_type=args.data_type, stride='full', start_date='2000-01-01', end_date='2018-01-01')

    print('train shape:', np.array(args.train_data).shape)
    print('val   shape:', np.array(args.val_data).shape)
    print('test  shape:', np.array(args.test_data).shape)

    ''' Define baselines and the grid of parameters '''
    nhidden_grid = [8, 16, 32]
    tcorex_gamma_grid = [1.25, 1.5, 2.0, 3.0, 4.0]

    methods = [
        (baselines.Diagonal(name='Diagonal'), {}),

        (baselines.LedoitWolf(name='Ledoit-Wolf'), {}),

        (baselines.OAS(name='Oracle approximating shrinkage'), {}),

        (baselines.PCA(name='PCA'), {'n_components': nhidden_grid}),

        (baselines.SparsePCA(name='SparsePCA'), {
            'n_components': [args.m],
            'alpha': [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0],
            'ridge_alpha': [0.01],
            'tol': 1e-6,
            'max_iter': 500,
        }),

        (baselines.FactorAnalysis(name='Factor Analysis'), {'n_components': nhidden_grid}),

        (baselines.LinearCorex(name='Linear CorEx (applied bucket-wise)'), {
            'n_hidden': nhidden_grid,
            'max_iter': 500,
            'anneal': True}),

        (baselines.LinearCorexWholeData(name='Linear CorEx (applied on whole data)'), {
            'n_hidden': nhidden_grid,
            'max_iter': 500,
            'anneal': True}),

        (baselines.GraphLasso(name='Graphical LASSO (sklearn)'), {
            'alpha': [0.003, 0.01, 0.03, 0.1, 0.3, 1.0],
            'mode': 'lars',
            'max_iter': 100}),

        (baselines.TimeVaryingGraphLasso(name='T-GLASSO'), {
            'lamb': [0.01, 0.03, 0.1, 0.3],
            'beta': [0.03, 0.1, 0.3, 1.0],
            'indexOfPenalty': [1],  # TODO: extend grid of this one; NOTE: L2 is slow and not efficient
            'max_iter': 100}),

        (baselines.TimeVaryingGraphLasso(name='T-GLASSO (no reg)'), {
            'lamb': [0.003, 0.01, 0.03, 0.1, 0.3, 1.0],
            'beta': [0.0],
            'indexOfPenalty': [1],
            'max_iter': 100}),

        (baselines.TCorex(tcorex=TCorex, name='T-Corex (W)'), {
            'nv': args.nv,
            'n_hidden': nhidden_grid,
            'max_iter': 500,
            'anneal': True,
            'reg_params': {
                'l2': [],
                'l1': [0.001, 0.01, 0.1, 1.0, 10.0, 100.0],
            },
            'reg_type': 'W'
        }),

        (baselines.TCorex(tcorex=TCorexWeights, name='T-Corex (W, weighted samples, no reg)'), {
            'nv': args.nv,
            'n_hidden': nhidden_grid,
            'max_iter': 500,
            'anneal': True,
            'l1': [0.0],
            'l2': 0.0,
            'gamma': tcorex_gamma_grid,
            'reg_type': 'W',
            'init': True
        }),

        (baselines.TCorex(tcorex=TCorexWeights, name='T-Corex (W, weighted samples)'), {
            'nv': args.nv,
            'n_hidden': nhidden_grid,
            'max_iter': 500,
            'anneal': True,
            'reg_params': {
                # 'l1': [0, 0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0],
                'l1': [0.001, 0.01, 0.1, 1.0, 10.0, 100.0],
                'l2': [],
            },
            'gamma': tcorex_gamma_grid,
            'reg_type': 'W',
            'init': True
        }),

        (baselines.TCorex(tcorex=TCorexWeights, name='T-Corex (W, weighted samples, no init)'), {
            'nv': args.nv,
            'n_hidden': [args.m],
            'max_iter': 500,
            'anneal': True,
            'reg_params': {
                # 'l1': [0, 0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0],
                'l1': [0.0, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0],
                'l2': [],
            },
            'gamma': tcorex_gamma_range,
            'reg_type': 'W',
            'init': False
        }),

        (baselines.QUIC(name='QUIC'), {
            'lamb': [0.001, 0.003, 0.01, 0.03, 0.1, 0.3, 1, 3],
            'tol': 1e-6,
            'msg': 1,  # NOTE: 0 - no verbosity; 1 - just two lines; 2 - max verbosity
            'max_iter': 100  # NOTE: tried 500, no improvement
        }),

        (baselines.BigQUIC(name='BigQUIC'), {
            'lamb': [0.01, 0.03, 0.1, 0.3, 1, 3, 10.0, 30.0],
            'tol': 1e-3,
            'verbose': 1,  # NOTE: 0 - no verbosity; 1 - just two lines; 2 - max verbosity
            'max_iter': 100  # NOTE: tried 500, no improvement
        })
    ]

    exp_name = '{}.nt{}.nv{}.train_cnt{}.val_cnt{}.test_cnt{}'.format(args.data_type, args.nt, args.nv,
                                                                      args.train_cnt, args.val_cnt, args.test_cnt)
    exp_name = args.prefix + exp_name
    results_path = "results/{}.results.json".format(exp_name)
    make_sure_path_exists(results_path)

    results = {}
    for (method, params) in methods[:]:
        name = method.name
        try:
            best_score, best_params, _, _ = method.select(args.train_data, args.val_data, params)
            results[name] = {}
            results[name]['test_score'] = method.evaluate(args.test_data, best_params)
            results[name]['best_params'] = best_params
            results[name]['best_val_score'] = best_score

            with open(results_path, 'w') as f:
                json.dump(results, f)
        except Exception as e:
            print('Could not run method {}, expection with message {}'.format(name, e.message))

    print("Results are saved in {}".format(results_path))


if __name__ == '__main__':
    main()
