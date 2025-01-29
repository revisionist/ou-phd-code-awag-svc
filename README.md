# AwAg Services

[![License: BSD-3-Clause-Clear](https://img.shields.io/badge/License-BSD--3--Clause--Clear-orange?style=flat-square)](https://spdx.org/licenses/BSD-3-Clause-Clear.html)

This repository contains application source code relating to the PhD Thesis by David Goddard, The Open University, 2025.

**AwAg Services (awag-svc)** is a Python Flask application designed to support research into the Awareness Agent application. This project is licensed under the [BSD 3-Clause Clear License](https://spdx.org/licenses/BSD-3-Clause-Clear.html).

This application was developed to support academic research and is shared 'as is' to allow others to view, use, and adapt the code in accordance with the license. However, it comes with no warranty of any kind, express or implied, including but not limited to warranties of merchantability or fitness for a particular purpose. Please note that no support or maintenance is provided for this code.  However, I am happy to answer questions about it if I can.


## Services

This application implements two primary services: the **ML Service** and the **Data Service**.

### ML Service
The **ML Service** provides limited machine learning capabilities, including model and data management.

#### Key Features:
1. **Classifier**:
   - Built using the [scikit-learn](https://scikit-learn.org/)  library.
   - Uses a `SGDClassifier` (linear SVM with stochastic gradient descent), configured with:
       - Loss function: `modified_huber`
       - Penalty: `l1`
       - Alpha: `1e-5`
       - Random state: `42`
       - Maximum iterations: `5`

2. **Model Management**:
   - Organises models and classifications in a structured directory hierarchy.
   - Manages training data for each classification, stored in text files.
   - Retrains models on startup or when new training data is added.

### Data Service
The **Data Service** provides data management and processing capabilities for the Awarness Agent applications and research project.

#### High-Level Routes:
1. **Core Functionality**:
   - `/data/class`: Records classification actions, feedback, and training data.
   - `/data/flow`: Records flow monitor data.
   - `/data/maintain`: Handles data management tasks, such as purging agent data.
   - `/data/misc`: Provides utility functions like tag retrieval.
   - `/data/summ`: Records summarisation requests and feedback.

2. **Evaluation and Study Support**:
   - `/data/chat`: Handles OpenAI chat requests using fine-tuned models.
   - `/data/eval`: Perdforms Synthetic Evaluation operations using OpenAI and also data and failure records.
   - `/data/fixit`: Ad hoc data recovery and reconstruction.
   - `/data/gentrain`: Generates fine-tuning data for OpenAI training.
   - `/data/reporting`: Prepares study data for reporting and analysis.
   - `/data/sim`: Generates and queries simulated data.
   - `/data/stats`: Computes statistics for study data.
   - `/data/subsets`: Manages subsets of data for evaluation.
   - `/data/train`: Manages and processes data sets for fine-tuning in OpenAI; manages OpenAI FT objects.


## Dependencies

This application uses the [Simple Persistent Object Store Service](https://github.com/revisionist/python-apps/tree/main/flask/sposs) for object storage, mainly in relation to managing OpenAI fine-tuning training objects.

It also uses a bespoke set of Python utility classes, [domestique](https://github.com/revisionist/python-utils/tree/main/domestique).  Other dependencies are as per the requirements file.


## License

This project is licensed under the **BSD 3-Clause Clear License**. See the [LICENSE-BSD](LICENSE-BSD) file for details.

### Acknowledgments
This project includes code based on the [Flask Boilerplate](https://github.com/idris-rampurawala/flask-boilerplate) by Idris Rampurawala, originally licensed under the MIT License. See [LICENSE-MIT](LICENSE-MIT) for details.
