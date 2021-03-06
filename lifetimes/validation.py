from __future__ import print_function
from __future__ import absolute_import
import lifetimes.generate_data as gen
import lifetimes.estimation as est
from lifetimes.data_compression import compress_bgext_data
from .utils import multinomial_sample
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from functools import reduce


def generate_neg_likelihoods(fitter,
                             test_ts=None,
                             penalizer_coef=0.1, size=100, simulation_size=100, refit=True):
    """
    Generates <simulation_size> log-likelihoods of BG model.
    To test goodness of model.
    Use refit=True if you're testing on fitted data [dafault].
    Use refit=False if you divided your dataset in training/test, this runs much faster.
    """

    n_lls = []
    params = fitter.params_

    for i in range(simulation_size):
        if test_ts:
            gen_data = fitter.generate_new_data(size=size, compressed=True, ts=test_ts)
        else:
            gen_data = fitter.generate_new_data(size=size, compressed=True)
        current_fitter = fitter.__class__(penalizer_coef=penalizer_coef)
        if refit:
            current_fitter.fit(**gen_data)
            n_lls.append(current_fitter._negative_log_likelihood_)
        else:
            n_ll = current_fitter._negative_log_likelihood(params=params.values(),
                                                   penalizer_coef=penalizer_coef,
                                                   **gen_data)
            n_lls.append(n_ll)

    return np.array(n_lls)


def goodness_of_test(data,
                     fitter_class,
                     penalizer_coef=0.1, simulation_size=100, confidence_level=0.99, verbose=False, test_data=None):
    """
    Returns True if data are compatible with the fitter distribution.
    """

    # fit them
    fitter = fitter_class(penalizer_coef=penalizer_coef)
    fitter.fit(**data)
    params = fitter.params_
    if test_data is None:
        n_ll = fitter._negative_log_likelihood_
        n_lls = generate_neg_likelihoods(fitter=fitter,
                                         simulation_size=simulation_size,
                                         refit=True)
    else:
        n_ll = fitter._negative_log_likelihood(
            params=params.values(),
            penalizer_coef=penalizer_coef,
            **test_data
        )
        n_lls = generate_neg_likelihoods(fitter=fitter,
                                         simulation_size=simulation_size,
                                         test_ts=reduce(lambda res, el: res + el,
                                                        [[t] * n for t, n in zip(test_data['T'], test_data['N'])], []),
                                         refit=False)

    # perform goodness of fit test
    lwr, upr = np.percentile(n_lls, [(1 - confidence_level) * 100, confidence_level * 100])

    if verbose:
        print("Bounds: " + str((lwr, upr)))
        print("Value: " + str(n_ll))

    if lwr < n_ll < upr:
        return True
    return False


def split_dataset(data, test_size_ratio):
    test_N = []
    train_N = []
    for i, n in enumerate(data['N']):
        test_N.append(0)
        train_N.append(0)
        for _ in range(n):
            if np.random.uniform() < test_size_ratio:
                test_N[i] += 1
            else:
                train_N[i] += 1
    test_data = data.copy(deep=True)
    test_data['N'] = test_N
    test_data = test_data[test_data['N'] > 0]
    train_data = data.copy(deep=True)
    train_data['N'] = train_N
    train_data = train_data[train_data['N'] > 0]
    return train_data, test_data




if __name__ == "__main__":
    params = {'alpha': 0.32, 'beta': 0.85}

    gen_data = compress_bgext_data(gen.bgext_model(T=[2] * 1000 + [3] * 1000
                                                     + [4] * 1000 + [5] * 1000
                                                     + [6] * 1000 + [7] * 1000,
                                                   alpha=params['alpha'],
                                                   beta=params['beta']))

    test_n = multinomial_sample(gen_data['N'])
    test_data = gen_data.copy(deep=True)
    test_data['N'] = test_n
    print(goodness_of_test(
        data=gen_data,
        fitter_class=est.BGFitter,
        test_data=test_data,
        verbose=True))

    # simulation_size = 100
    # N_users = 10000
    # T_horizon = 10
    # n_lls = generate_BG_neg_likelihoods(params['alpha'], params['beta'], T=T_horizon, size=N_users,
    #                                     simulation_size=simulation_size)
    #
    # plt.hist(n_lls, 50, normed=0, facecolor='g', alpha=0.75)
    #
    # plt.xlabel('negative log_likelihood estimates')
    # plt.title(
    #     'Histogram of negative log_likelihood estimates - ' + str(N_users) + ' users, T: ' + str(
    #         T_horizon) + ' - params: ' + str(params))
    #
    # # plt.axvline(x=true_Ex, color="red")
    # plt.grid(True)
    # print "Enjoy the plot!"
    # plt.show()
