// This is lifting heavily from https://github.com/shssoichiro/ffmpeg-the-third/blob/master/examples/dump-frames.rs
use ffmpeg_the_third as ffmpeg;

use aruco3::{ARDictionary, Detector, DetectorConfig, Detection, pose, CameraIntrinsics};
use clap::Parser;
use crate::ffmpeg::format::{input, Pixel};
use crate::ffmpeg::media::Type;
use crate::ffmpeg::software::scaling::{context::Context, flag::Flags};
use crate::ffmpeg::util::frame::video::Video;
use image;

#[derive(Parser, Debug)]
#[command(version, about, long_about = None)]
struct Args {
	/// The path to the video to read.
	filename: String,

	/// The type of fiducial markers to use.
	fiducial_dictionary: String,

	/// The length of the edge of the fiducial markers in mm.
	marker_size_mm: f32,

	/// If 'true', print lots of information.
	#[arg(short, long, default_value_t = false)]
	verbose: bool,

	/// If 'true', print all supported dictionaries and halt.
	#[arg(long, default_value_t = false)]
	print_supported_dictionaries: bool,

	/// The starting frame from which to dump fiducial tracks.
	#[arg(long, default_value_t = 0)]
	start_frame: u64,

	/// The ending frame (exclusive) to which fiducial markers should be detected.
	#[arg(long, default_value_t = 0)]
	end_frame: u64,

	/// The horizontal focal length of the camera in mm.
	#[arg(long, default_value_t = 1f32)]
	focal_length_mm: f32,

	/// The size of the sensor (diagonal) in mm.
	#[arg(long)]
	sensor_size_mm: Option<f32>,

	/// The field of view of the camera in radians.
	#[arg(long)]
	fov_h_radians: Option<f32>,
}

fn main() -> Result<(), ffmpeg::Error> {
	ffmpeg::init().unwrap();

	let args = Args::parse(); // Better than env::args().nth(1).expect("Cannot open file.")

	if args.print_supported_dictionaries {
		for d in ARDictionary::get_dictionary_names() {
			println!("{}", d);
		}
		return Ok(());
	}

	let dictionary = ARDictionary::new_from_named_dict(&args.fiducial_dictionary);
	let detector = Detector {
		config: DetectorConfig::default(),
		dictionary,
	};

	if let Ok(mut ictx) = input(args.filename) {
		let input = ictx
			.streams()
			.best(Type::Video)
			.ok_or(ffmpeg::Error::StreamNotFound)?;
		let video_stream_index = input.index();

		let mut context_decoder =
			ffmpeg::codec::context::Context::from_parameters(input.parameters())?;

		if let Ok(parallelism) = std::thread::available_parallelism() {
			context_decoder.set_threading(ffmpeg::threading::Config {
				kind: ffmpeg::threading::Type::Frame,
				count: parallelism.get().min(16), // FFMPEG does not recommend more than 16 threads.
			});
		}

		let mut decoder = context_decoder.decoder().video()?;

		let mut scaler = Context::get(
			decoder.format(),
			decoder.width(),
			decoder.height(),
			Pixel::RGB24,
			decoder.width(),
			decoder.height(),
			Flags::BILINEAR,
		)?;
		
		let intrinsics = if args.fov_h_radians.is_some() && args.sensor_size_mm.is_some() {
			let hfov = args.fov_h_radians.unwrap();
			let sensor_width_mm = args.sensor_size_mm.unwrap(); // TODO: This is not HW, necessarily. This might be diagonal width.
			CameraIntrinsics::new_from_fov_horizontal(hfov, sensor_width_mm, decoder.width(), decoder.height())
		} else {
			CameraIntrinsics::new(decoder.width(), decoder.height(), args.focal_length_mm, args.focal_length_mm, None, None)
		};

		let mut frame_index = 0;

		let mut receive_and_process_decoded_frames =
			|decoder: &mut ffmpeg::decoder::Video| -> Result<(), ffmpeg::Error> {
				let mut decoded = Video::empty();
				while decoder.receive_frame(&mut decoded).is_ok() && (args.end_frame == 0 || frame_index < args.end_frame as usize) {
					if frame_index >= args.start_frame as usize {
						let mut rgb_frame = Video::empty();
						scaler.run(&decoded, &mut rgb_frame)?;
						//save_file(&rgb_frame, frame_index).unwrap();
						let img: image::RgbImage = image::RgbImage::from_raw(rgb_frame.width(), rgb_frame.height(), rgb_frame.data(0).to_vec()).expect("Failed to decode video frame with index {index}");
						let detections = detector.detect(img.into());
						println!("{}", detections_to_jsonl(frame_index, &detections, args.marker_size_mm, &intrinsics));
					}
					frame_index += 1;
				}
				Ok(())
			};

		for (stream, packet) in ictx.packets().filter_map(Result::ok) {
			if stream.index() == video_stream_index {
				decoder.send_packet(&packet)?;
				receive_and_process_decoded_frames(&mut decoder)?;
			}
		}
		decoder.send_eof()?;
		receive_and_process_decoded_frames(&mut decoder)?;
	}

	Ok(())
}

/*
fn save_file(frame: &Video, index: usize) -> std::result::Result<(), std::io::Error> {
	let mut file = File::create(format!("frame{index}.ppm"))?;
	file.write_all(format!("P6\n{} {}\n255\n", frame.width(), frame.height()).as_bytes())?;
	file.write_all(frame.data(0))?;
	Ok(())
}
*/

// Convert a detection into a single-line JSON output.
// We could use serde_json, but it feels like overkill.
fn detections_to_jsonl(frame_idx: usize, detection: &Detection, marker_size_mm: f32, camera_intrinsics: &CameraIntrinsics) -> String {
	let mut out = String::with_capacity(1024);
	out.push_str("{");
	out.push_str(&format!("\"frame_id\":{},", frame_idx));
	out.push_str("\"detections\":[");
	let marker_count = detection.markers.len();
	for (idx, m) in detection.markers.iter().enumerate() {
		let (mp1, mp2) = pose::solve_with_intrinsics(&m.corners, marker_size_mm, camera_intrinsics);
		out.push_str("{");
		out.push_str(&format!("\"marker_id\":{},", m.id));
		out.push_str(&format!("\"corners\":[{},{},{},{},{},{},{},{}],", m.corners[0].0, m.corners[0].1, m.corners[1].0, m.corners[1].1, m.corners[2].0, m.corners[2].1, m.corners[3].0, m.corners[3].1));
		out.push_str("\"poses\":[");
		for (mp, endl) in [mp1, mp2].iter().zip([",", ""]) {
			out.push_str("{");
			out.push_str(&format!("\"translation\":[{},{},{}],", mp.translation.x, mp.translation.y, mp.translation.z));
			out.push_str(&format!("\"rotation\":[{},{},{},{},{},{},{},{},{}],", mp.rotation.m11, mp.rotation.m12, mp.rotation.m13, mp.rotation.m21, mp.rotation.m22, mp.rotation.m23, mp.rotation.m31, mp.rotation.m32, mp.rotation.m33));
			out.push_str(&format!("\"error\":{}", mp.error));
			out.push_str("}");
			out.push_str(endl);
		}
		out.push_str("]");
		out.push_str("}");
		if marker_count > 1 && idx < marker_count-1 {
			out.push_str(",");
		}
	}
	out.push_str("]");
	out.push_str("}");
	out
}

#[cfg(test)]
mod tests {
	#[test]
	fn test_sanity() {
	}
}
