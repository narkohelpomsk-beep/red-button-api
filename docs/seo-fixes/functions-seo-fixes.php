<?php
/**
 * Plugin Name: Impulse SEO fixes
 * Description: NGO/LocalBusiness schema, FAQPage, no SearchAction, H1 on calculator, noindex cyrillic news slugs.
 * Version: 1.0.0
 *
 * How to install (pick one):
 * 1. Code Snippets plugin → Add snippet → paste this file (without the Plugin Name header if the plugin wraps it) → Run everywhere.
 * 2. Child theme functions.php → require_once this file.
 * 3. wp-content/mu-plugins/impulse-seo-fixes.php
 *
 * After install: WP Rocket → clear cache. Then view-source the homepage and check JSON-LD.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

const IMPULS_SEO_ORG_DESC = 'АНО «ЦСП «Импульс»»: социальная реабилитация зависимости в Омске от 45 000 ₽/мес. Консультации 24/7, анонимно. Медицинские услуги оказывает лицензированный партнёр.';
const IMPULS_SEO_PAGE_TITLE = 'Реабилитационный центр «Импульс» в Омске — помощь при зависимости';
const IMPULS_SEO_H1 = 'Реабилитационный центр «Импульс» в Омске';
const IMPULS_SEO_2GIS = 'https://2gis.ru/omsk/firm/70000001033512039';
const IMPULS_SEO_OG_IMAGE = '/wp-content/uploads/og-image-1200x630.jpg';

/**
 * 1. Yoast: drop SearchAction (search URLs are Disallow: /?s= in robots.txt).
 */
add_filter(
	'wpseo_schema_website',
	static function ( $data ) {
		if ( is_array( $data ) && isset( $data['potentialAction'] ) ) {
			unset( $data['potentialAction'] );
		}
		return $data;
	}
);

/**
 * 2. Yoast: homepage WebPage name/description must not promise medication treatment.
 */
add_filter(
	'wpseo_schema_webpage',
	static function ( $data ) {
		if ( ! is_front_page() || ! is_array( $data ) ) {
			return $data;
		}
		$data['name']        = IMPULS_SEO_PAGE_TITLE;
		$data['description'] = IMPULS_SEO_ORG_DESC;
		return $data;
	}
);

/**
 * 3. Yoast: do not emit a one-item BreadcrumbList on the homepage.
 */
add_filter(
	'wpseo_schema_breadcrumb',
	static function ( $data ) {
		if ( is_front_page() ) {
			return false;
		}
		return $data;
	}
);

/**
 * 4. Yoast Organization piece: force NGO identity if Yoast still outputs Organization.
 */
add_filter(
	'wpseo_schema_organization',
	static function ( $data ) {
		if ( ! is_array( $data ) ) {
			return $data;
		}
		$data['@type']         = array( 'NGO', 'LocalBusiness' );
		$data['name']          = 'АНО «ЦСП «Импульс»»';
		$data['legalName']     = 'Автономная некоммерческая организация «Центр социальной помощи «Импульс»»';
		$data['taxID']         = '5504151921';
		$data['description']   = IMPULS_SEO_ORG_DESC;
		$data['sameAs']        = array(
			IMPULS_SEO_2GIS,
			'https://vk.com/impuls_omsk',
			'https://t.me/impuls_red_bot',
			'https://impulsplus55.ru/',
		);
		$data['address']       = array(
			'@type'           => 'PostalAddress',
			'streetAddress'   => 'ул. Декабристов, 37, оф. 25',
			'addressLocality' => 'Омск',
			'addressRegion'   => 'Омская область',
			'postalCode'      => '644070',
			'addressCountry'  => 'RU',
		);
		return $data;
	}
);

/**
 * 5. Print NGO + FAQPage JSON-LD (theme MedicalClinic block is stripped in the buffer below).
 */
add_action(
	'wp_footer',
	static function () {
		$schema_dir = dirname( __FILE__ );
		// When pasted into Code Snippets, dirname(__FILE__) is not this repo. Fallback: inline.
		$org = null;
		$faq = null;
		$org_path = $schema_dir . '/schema-homepage.json';
		$faq_path = $schema_dir . '/schema-faqpage.json';
		if ( is_readable( $org_path ) ) {
			$org = json_decode( file_get_contents( $org_path ), true );
		}
		if ( is_readable( $faq_path ) && is_front_page() ) {
			$faq = json_decode( file_get_contents( $faq_path ), true );
		}

		if ( ! $org ) {
			$org = array(
				'@context' => 'https://schema.org',
				'@type'    => array( 'NGO', 'LocalBusiness' ),
				'@id'      => home_url( '/#organization' ),
				'name'     => 'АНО «ЦСП «Импульс»»',
				'url'      => home_url( '/' ),
				'telephone'=> array( '+7-3812-387-927', '+7-909-535-40-90' ),
				'email'    => 'rc-impuls@yandex.ru',
				'taxID'    => '5504151921',
				'address'  => array(
					'@type'           => 'PostalAddress',
					'streetAddress'   => 'ул. Декабристов, 37, оф. 25',
					'addressLocality' => 'Омск',
					'addressRegion'   => 'Омская область',
					'postalCode'      => '644070',
					'addressCountry'  => 'RU',
				),
				'geo'      => array(
					'@type'     => 'GeoCoordinates',
					'latitude'  => '54.989347',
					'longitude' => '73.368221',
				),
				'sameAs'   => array(
					IMPULS_SEO_2GIS,
					'https://vk.com/impuls_omsk',
					'https://t.me/impuls_red_bot',
					'https://impulsplus55.ru/',
				),
				'description' => IMPULS_SEO_ORG_DESC,
			);
		}

		echo '<script type="application/ld+json">' . wp_json_encode( $org, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES ) . "</script>\n";

		if ( is_front_page() ) {
			if ( ! $faq ) {
				$faq = array(
					'@context'   => 'https://schema.org',
					'@type'      => 'FAQPage',
					'@id'        => home_url( '/#faq' ),
					'mainEntity' => array(
						array(
							'@type'          => 'Question',
							'name'           => 'Можно ли пройти лечение анонимно?',
							'acceptedAnswer' => array(
								'@type' => 'Answer',
								'text'  => 'Да. Консультация и подбор формата помощи возможны без передачи данных третьим лицам. На очном этапе нужны документы по требованию закона — заранее объясним, что именно и зачем.',
							),
						),
						array(
							'@type'          => 'Question',
							'name'           => 'Что делать, если человек отказывается лечиться?',
							'acceptedAnswer' => array(
								'@type' => 'Answer',
								'text'  => 'Давление обычно ухудшает ситуацию. Начните с бесплатной консультации для родственников: разберём безопасную тактику разговора и первые шаги.',
							),
						),
						array(
							'@type'          => 'Question',
							'name'           => 'Сколько длится реабилитация?',
							'acceptedAnswer' => array(
								'@type' => 'Answer',
								'text'  => 'Ориентир — от 6 месяцев; точный срок зависит от диагноза, срывов и динамики.',
							),
						),
						array(
							'@type'          => 'Question',
							'name'           => 'Можно ли навещать родственника во время программы?',
							'acceptedAnswer' => array(
								'@type' => 'Answer',
								'text'  => 'Правила визитов и звонков зависят от этапа программы и состояния человека — их согласовываем индивидуально с куратором.',
							),
						),
						array(
							'@type'          => 'Question',
							'name'           => 'Что входит в стоимость?',
							'acceptedAnswer' => array(
								'@type' => 'Answer',
								'text'  => 'В стоимость входят программа проживания/наблюдения по выбранному формату, работа специалистов и базовый набор процедур по плану.',
							),
						),
						array(
							'@type'          => 'Question',
							'name'           => 'Есть ли помощь после выписки?',
							'acceptedAnswer' => array(
								'@type' => 'Answer',
								'text'  => 'Да, доступно постреабилитационное сопровождение: закрепление навыков, профилактика срывов, контакт с куратором по договорённости.',
							),
						),
						array(
							'@type'          => 'Question',
							'name'           => 'Как быстро можно начать лечение?',
							'acceptedAnswer' => array(
								'@type' => 'Answer',
								'text'  => 'Первичная консультация — в день обращения. Сроки поступления в программу зависят от заполненности мест и медицинских показаний.',
							),
						),
					),
				);
			}
			echo '<script type="application/ld+json">' . wp_json_encode( $faq, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES ) . "</script>\n";
		}
	},
	20
);

/**
 * 6. Strip theme MedicalClinic + broken SearchAction + wrong 2GIS ID from final HTML.
 * Purge WP Rocket after activating. Cached HTML is rewritten on the next generate.
 */
add_action(
	'template_redirect',
	static function () {
		if ( is_admin() || wp_doing_ajax() || wp_doing_cron() ) {
			return;
		}
		ob_start( 'impuls_seo_rewrite_html' );
	},
	0
);

function impuls_seo_rewrite_html( $html ) {
	if ( ! is_string( $html ) || $html === '' ) {
		return $html;
	}

	$html = str_replace( '"@type":"MedicalClinic"', '"@type":["NGO","LocalBusiness"]', $html );
	$html = str_replace( '"@type": "MedicalClinic"', '"@type": ["NGO","LocalBusiness"]', $html );
	$html = str_replace( 'https://account.2gis.com/orgs/70000001033512038', IMPULS_SEO_2GIS, $html );
	$html = str_replace( '70000001033512038', '70000001033512039', $html );
	$html = str_replace( 'медикаментозное лечение', 'социальную реабилитацию', $html );
	$html = str_replace( '"postalCode":"644000"', '"postalCode":"644070"', $html );
	$html = str_replace( '"postalCode": "644000"', '"postalCode": "644070"', $html );

	$html = preg_replace(
		'/,"potentialAction":\[\{"@type":"SearchAction"[^]]*\]/',
		'',
		$html
	);

	return $html;
}

/**
 * 7. Calculator page /rasschitat-stoimost/ has no H1 in the template.
 */
add_filter(
	'the_content',
	static function ( $content ) {
		if ( ! is_page( 'rasschitat-stoimost' ) ) {
			return $content;
		}
		if ( preg_match( '/<h1[\s>]/i', $content ) ) {
			return $content;
		}
		$h1 = '<h1 class="impuls-calc-h1">Рассчитать стоимость реабилитации в Омске</h1>';
		return $h1 . $content;
	},
	5
);

/**
 * 8. Noindex news with Cyrillic or emoji slugs (keep follow so internal links still pass some equity).
 */
add_filter(
	'wpseo_robots',
	static function ( $robots ) {
		if ( ! impuls_seo_is_bad_news_slug() ) {
			return $robots;
		}
		$robots = preg_replace( '/\bindex\b/', 'noindex', $robots );
		if ( strpos( $robots, 'noindex' ) === false ) {
			$robots = 'noindex, follow';
		}
		return $robots;
	}
);

add_filter(
	'wpseo_exclude_from_sitemap_by_post_ids',
	static function ( $ids ) {
		$query = new WP_Query(
			array(
				'post_type'      => array( 'news', 'post' ),
				'posts_per_page' => 200,
				'fields'         => 'ids',
				'no_found_rows'  => true,
			)
		);
		foreach ( $query->posts as $id ) {
			$slug = get_post_field( 'post_name', $id );
			if ( impuls_seo_slug_is_bad( rawurldecode( $slug ) ) ) {
				$ids[] = (int) $id;
			}
		}
		return array_values( array_unique( array_map( 'intval', $ids ) ) );
	}
);

function impuls_seo_is_bad_news_slug() {
	if ( ! is_singular() ) {
		return false;
	}
	$type    = get_post_type();
	$uri     = isset( $_SERVER['REQUEST_URI'] ) ? wp_unslash( $_SERVER['REQUEST_URI'] ) : '';
	$is_news = ( $type === 'news' ) || ( is_string( $uri ) && strpos( $uri, '/news/' ) !== false );
	if ( ! $is_news ) {
		return false;
	}
	$slug = rawurldecode( (string) get_post_field( 'post_name', get_the_ID() ) );
	return impuls_seo_slug_is_bad( $slug );
}

function impuls_seo_slug_is_bad( $slug ) {
	if ( $slug === '' ) {
		return false;
	}
	if ( preg_match( '/\p{Cyrillic}/u', $slug ) ) {
		return true;
	}
	if ( preg_match( '/[\x{1F300}-\x{1FAFF}]/u', $slug ) ) {
		return true;
	}
	return false;
}

/**
 * 9. Front page Open Graph image size after the file is uploaded to the Media Library.
 * Until then Yoast still uses intro_page_1.png — upload og-image-1200x630.jpg and set it
 * in Yoast → Search Appearance → Social OR the homepage social preview.
 */
add_filter(
	'wpseo_opengraph_image',
	static function ( $url ) {
		if ( is_front_page() ) {
			$candidate = home_url( IMPULS_SEO_OG_IMAGE );
			return $candidate;
		}
		return $url;
	}
);

add_filter(
	'wpseo_opengraph_image_width',
	static function ( $w ) {
		return is_front_page() ? 1200 : $w;
	}
);

add_filter(
	'wpseo_opengraph_image_height',
	static function ( $h ) {
		return is_front_page() ? 630 : $h;
	}
);
