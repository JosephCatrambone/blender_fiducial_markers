// Build: g++ -Wall main.cpp -I/usr/include/opencv4 -I `pkg-config --libs --cflags opencv4` -o main
#include <opencv2/opencv.hpp>
#include <opencv2/aruco.hpp>
#include <opencv2/calib3d.hpp>
#include <iostream>
#include <cmath>
#include <string>
#include <string_view>
#include <cstring>
#include <vector>

// To be explicit about mixing std::vector and cv::vec, we should comment out namespace.
//using namespace std;

struct RunConfiguration {
	std::string mediaFilepath;
	std::string dictionaryName;
	float markerSizeMM;
	float cameraFocalLengthMM;
	uint startFrame;
	uint endFrame;
	bool quit;
	bool printEmptyFrames;
	std::string errorMessage;
};

RunConfiguration parseArgs(int, char**);
bool startsWith(std::string, const char*);
cv::Ptr<cv::aruco::Dictionary> getDictFromName(std::string);
void printJSONL(int, std::vector<int>, std::vector<std::vector<cv::Point2f>>, std::vector<cv::Vec3d>, std::vector<cv::Vec3d>);

int main(int argc, char** argv) {
	RunConfiguration cfg = parseArgs(argc, argv);
	if(cfg.quit) {
		std::cerr << cfg.errorMessage << std::endl;
		return -1;
	}

	// Open video file and seek to the start frame.
	cv::VideoCapture video(cfg.mediaFilepath);
	cv::Mat frame;
	if(!video.isOpened()) {
		std::cerr << "Failed to open video stream " << cfg.mediaFilepath << std::endl;
		return -1;
	}
	for(int i=0; i < cfg.startFrame; i++) {
		if(!video.read(frame)) {
			std::cerr << "Start frame was greater than video length." << std::endl;
			return -1;
		}
	}

	// For more on this, see https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html
	// Initialize detector and the start fiducial.
	cv::Ptr<cv::aruco::Dictionary> dictionary = getDictFromName(cfg.dictionaryName);
	// Old: cv::aruco::Dictionary dictionary = cv::aruco::getPredefinedDictionary(cv::aruco::DICT_6X6_250);
	cv::Mat objPoints(4, 1, CV_32FC3);
    objPoints.ptr<cv::Vec3f>(0)[0] = cv::Vec3f(-cfg.markerSizeMM/2.f, cfg.markerSizeMM/2.f, 0);
    objPoints.ptr<cv::Vec3f>(0)[1] = cv::Vec3f(cfg.markerSizeMM/2.f, cfg.markerSizeMM/2.f, 0);
    objPoints.ptr<cv::Vec3f>(0)[2] = cv::Vec3f(cfg.markerSizeMM/2.f, -cfg.markerSizeMM/2.f, 0);
    objPoints.ptr<cv::Vec3f>(0)[3] = cv::Vec3f(-cfg.markerSizeMM/2.f, -cfg.markerSizeMM/2.f, 0);

	// Set up the camera intrinsics so we can undistort the image.
	cv::Mat cameraMatrix(3, 3, CV_32FC3);
	cameraMatrix.at<float>(0,0) = cfg.cameraFocalLengthMM;
	cameraMatrix.at<float>(0,1) = 0.0; // No skew.
	cameraMatrix.at<float>(0,2) = frame.cols/2.0; // Optical center.
	cameraMatrix.at<float>(1,0) = 0.0;
	cameraMatrix.at<float>(1,1) = cfg.cameraFocalLengthMM;
	cameraMatrix.at<float>(1,2) = frame.rows/2.0;
	cameraMatrix.at<float>(2,0) = 0.0;
	cameraMatrix.at<float>(2,1) = 0.0;
	cameraMatrix.at<float>(2,2) = 1.0;
	// Configure camera distortion params.
	cv::Mat cameraDistortion(4, 1, CV_32F);
	cameraDistortion.at<float>(0) = 0.0;
	cameraDistortion.at<float>(1) = 0.0;
	cameraDistortion.at<float>(2) = 0.0;
	cameraDistortion.at<float>(3) = 0.0;

	// Allocate space for the results:
	std::vector<int> markerIds;
	std::vector<std::vector<cv::Point2f>> markerCorners, rejectedCandidates;
	//cv::aruco::DetectorParameters detectorParams = cv::aruco::DetectorParameters();
	// Old: cv::aruco::ArucoDetector detector(dictionary, detectorParams);
	for(int i=cfg.startFrame; i < cfg.endFrame || cfg.endFrame == 0; i++) {
		if(!video.read(frame)) {
			break;
		}

		//.cvtColor(frame, cv.COLOR_BGR2GRAY) ?
		cv::aruco::detectMarkers(frame, dictionary, markerCorners, markerIds);
		//detector.detectMarkers(frame, markerCorners, markerIds, rejectedCandidates);

		size_t markerCount = markerCorners.size();
        std::vector<cv::Vec3d> rvecs(markerCount), tvecs(markerCount);
 
        if(!markerIds.empty()) {
            for (size_t i = 0; i < markerCount; i++) {
                cv::solvePnP(objPoints, markerCorners.at(i), cameraMatrix, cameraDistortion, rvecs.at(i), tvecs.at(i));
            }
        } else if(cfg.printEmptyFrames) {
			std::cout << "{\"frame_id\":" << i << ", detections:[]}" << std::endl;
		}
	}

	video.release();
	return 0;
}

RunConfiguration parseArgs(int argc, char** argv) {
	RunConfiguration cfg;
	cfg.cameraFocalLengthMM = 1.0;
	cfg.startFrame = 0;
	cfg.endFrame = 0;
	cfg.quit = false;
	cfg.errorMessage = "";
	cfg.printEmptyFrames = false;

	// Check for "--help" and "-h"
	for(int i=0; i < argc; i++) {
		if(strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
			cfg.quit = true;
			cfg.errorMessage = "Usage: app path_to_mediafile dictionary_name marker_size_mm\nOptional Arguments: --focalmm=[The focal length of the camera in mm]\n";
			return cfg;
		}
	}

	// First three arguments should be filename, dictionary, and marker size.
	if(argc < 4) {
		cfg.errorMessage = "Not enough arguments. Usage: path_to_mediafile dictionary_name marker_size_mm";
		cfg.quit = true;
		return cfg;
	}
	cfg.mediaFilepath = argv[1];
	cfg.dictionaryName = argv[2];
	cfg.markerSizeMM = std::stof(argv[3]);

	// Check for extra arguments like focal length, distortion coefficients, etc.
	for(int i=4; i < argc; i++) {
		std::string arg = argv[i];
		if(startsWith(arg, "-v") || startsWith(arg, "--verbose")) {
			//cout << "VERBOSE!" << endl;
		}
		if(startsWith(arg, "--print-empty-frames")) {
			cfg.printEmptyFrames = true;
		}
	}

	return cfg;
}

bool startsWith(std::string str, const char* match) {
	int end = std::min(str.length(), strlen(match));
	for(int i=0; i < end; i++) {
		if(str[i] != match[i]) {
			return false;
		}
	}
	return true;
}

cv::Ptr<cv::aruco::Dictionary> getDictFromName(std::string name) {
	std::unordered_map<std::string, cv::aruco::PREDEFINED_DICTIONARY_NAME> supported;
	//supported["DEFAULT"] = cv::aruco::PREDEFINED_DICTIONARY_NAME::DICT_ARUCO_ORIGINAL;
	supported["DEFAULT"] = cv::aruco::DICT_ARUCO_ORIGINAL;
	supported["ARUCO"] = cv::aruco::DICT_ARUCO_ORIGINAL;
	supported["APRILTAG_16H5"] = cv::aruco::DICT_APRILTAG_16h5;
	supported["APRILTAG_25H9"] = cv::aruco::DICT_APRILTAG_25h9;
	supported["APRILTAG_36H10"] = cv::aruco::DICT_APRILTAG_36h10;
	supported["APRILTAG_36H11"] = cv::aruco::DICT_APRILTAG_36h11;
	return cv::aruco::getPredefinedDictionary(supported[name]);
}

void printJSONL(int frame, std::vector<int> markerIds, std::vector<std::vector<cv::Point2f>> markerCorners, std::vector<cv::Vec3d> markerTranslations, std::vector<cv::Vec3d> markerRotations) {
	std::cout << "{\"frame_id\":" << frame << ",\"detections\":[";
	for(int i=0; i < markerIds.size(); i++) {
		std::cout << "{";
		std::cout << "\"marker_id\":" << markerIds.at(i) << ",";
		//cout << "\"corners\":[" << markerCorners->at(i)
		std::cout << "}";
		if(i < markerIds.size()-1) {
			std::cout << ",";
		}
	}
	std::cout << "]}" << std::endl;
}